using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text.RegularExpressions;
using BepInEx;
using BepInEx.Configuration;
using BepInEx.Logging;
using HarmonyLib;
using UnityEngine;

namespace FlabOracle
{
    /// <summary>
    /// A ground-truth oracle for DSP blueprint-paste build conditions.
    ///
    /// This plugin contains ZERO reimplementation of game rules. It installs
    /// Harmony prefixes/postfixes that read what the game already decided and
    /// writes it to JSON. Every number in the dump was produced by the game.
    /// </summary>
    [BepInPlugin(PluginGuid, PluginName, PluginVersion)]
    public class OraclePlugin : BaseUnityPlugin
    {
        public const string PluginGuid = "org.dberlin.flab2bp.oracle";
        public const string PluginName = "flab2bp build-condition oracle";
        public const string PluginVersion = "1.2.0";

        private Harmony _harmony;

        private void Awake()
        {
            Oracle.Log = Logger;

            Oracle.DumpKey = Config.Bind(
                "Trigger",
                "DumpKey",
                new KeyboardShortcut(KeyCode.F9),
                "Press this while a blueprint preview is following the cursor to dump the current build-condition verdicts without building anything.");

            Oracle.StackingKey = Config.Bind(
                "Trigger",
                "StackingFactsKey",
                new KeyboardShortcut(KeyCode.F10),
                "Press this at any time (in a save, ideally) to dump the sorter cargo-stacking research table and the Automatic Piler facts. Needs no blueprint on the cursor.");

            Oracle.DumpOnPaste = Config.Bind(
                "Trigger",
                "DumpOnPaste",
                true,
                "Also dump automatically when the paste is committed (CreatePrebuilds). Produces two records per paste: createprebuilds-pre and createprebuilds-post.");

            Oracle.AlwaysCaptureColliders = Config.Bind(
                "Capture",
                "AlwaysCaptureColliderDetail",
                false,
                "Identify every collider that MatchInserter's overlap query returned, on EVERY frame rather than only on the armed frame. Makes the automatic paste dump carry snap-candidate detail too, at the cost of frame time while a blueprint is on the cursor.");

            Oracle.PatchPhysicsOverlap = Config.Bind(
                "Capture",
                "PatchPhysicsOverlap",
                true,
                "Hook the exact Physics.OverlapSphereNonAlloc and OverlapCapsuleNonAlloc overloads used by belt collision checks. Hooks are process-wide but return immediately outside an active semantic target capture.");

            Oracle.OutputDir = Config.Bind(
                "Output",
                "OutputDirectory",
                string.Empty,
                "Directory for dump files. Empty means <BepInEx>/flab2bp-oracle.");

            Oracle.ResolveOutputDirectory();

            _harmony = new Harmony(PluginGuid);
            try
            {
                _harmony.PatchAll(typeof(OraclePlugin).Assembly);
                Logger.LogInfo("Patched BuildTool_BlueprintPaste timeline (DeterminePreviewsPrestage, CheckBuildConditionsPrestage, ArrangeOverlapBP, ActiveColliders, CheckBuildConditions, AddErrorMessage, MatchInserter, CreatePrebuilds).");
            }
            catch (Exception e)
            {
                Logger.LogError("Failed to patch BuildTool_BlueprintPaste: " + e);
            }

            TryPatchOverlapSphere();
            TryPatchOverlapCapsule();

            Logger.LogMessage(
                "flab2bp oracle ready. Dump key = " + Oracle.DumpKey.Value +
                ", stacking-facts key = " + Oracle.StackingKey.Value +
                ", output = " + Oracle.OutputDirectory);
        }

        private void OnDestroy()
        {
            if (_harmony != null)
            {
                _harmony.UnpatchSelf();
                _harmony = null;
            }
        }

        /// <summary>
        /// Patch the exact Physics.OverlapSphereNonAlloc overload MatchInserter
        /// calls, so we can record the candidate count and the identity of each
        /// collider PhysX handed back. This is observation: the count is the
        /// engine's return value and the identities come from the game's own
        /// PlanetPhysics.GetColliderData.
        /// </summary>
        private void TryPatchOverlapSphere()
        {
            if (!Oracle.PatchPhysicsOverlap.Value)
            {
                Logger.LogInfo("PatchPhysicsOverlap is off; dumps will report overlapObserved=false.");
                return;
            }

            try
            {
                MethodInfo target = AccessTools.Method(
                    typeof(Physics),
                    "OverlapSphereNonAlloc",
                    new[]
                    {
                        typeof(Vector3),
                        typeof(float),
                        typeof(Collider[]),
                        typeof(int),
                        typeof(QueryTriggerInteraction)
                    });

                if (target == null)
                {
                    Logger.LogWarning(
                        "Physics.OverlapSphereNonAlloc(Vector3,float,Collider[],int,QueryTriggerInteraction) not found; " +
                        "dumps will report overlapObserved=false.");
                    return;
                }

                MethodInfo postfix = AccessTools.Method(typeof(PhysicsPatch), nameof(PhysicsPatch.OverlapSphereNonAllocPostfix));
                _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
                Oracle.OverlapPatchApplied = true;
                Logger.LogInfo("Patched Physics.OverlapSphereNonAlloc.");
            }
            catch (Exception e)
            {
                Logger.LogWarning(
                    "Could not patch Physics.OverlapSphereNonAlloc (" + e.Message + "); " +
                    "dumps will report overlapObserved=false. Everything else still works.");
            }
        }

        private void TryPatchOverlapCapsule()
        {
            if (!Oracle.PatchPhysicsOverlap.Value)
            {
                return;
            }

            try
            {
                MethodInfo target = AccessTools.Method(
                    typeof(Physics),
                    "OverlapCapsuleNonAlloc",
                    new[]
                    {
                        typeof(Vector3),
                        typeof(Vector3),
                        typeof(float),
                        typeof(Collider[]),
                        typeof(int),
                        typeof(QueryTriggerInteraction)
                    });
                if (target == null)
                {
                    Logger.LogWarning(
                        "Physics.OverlapCapsuleNonAlloc(Vector3,Vector3,float,Collider[],int,QueryTriggerInteraction) not found; " +
                        "automatic target captures will contain sphere queries only.");
                    return;
                }

                MethodInfo postfix = AccessTools.Method(typeof(PhysicsPatch), nameof(PhysicsPatch.OverlapCapsuleNonAllocPostfix));
                _harmony.Patch(target, postfix: new HarmonyMethod(postfix));
                Oracle.CapsulePatchApplied = true;
                Logger.LogInfo("Patched Physics.OverlapCapsuleNonAlloc.");
            }
            catch (Exception e)
            {
                Logger.LogWarning(
                    "Could not patch Physics.OverlapCapsuleNonAlloc (" + e.Message + "); " +
                    "automatic target captures will contain sphere queries only.");
            }
        }

        private void Update()
        {
            try
            {
                if (Oracle.DumpKey.Value.IsDown())
                {
                    Oracle.ArmHotkey();
                }

                // Unlike the paste dump this one needs no armed Harmony pass: every
                // fact it writes is already sitting in LDB, in the history, or on a
                // live component, so it is served on the spot.
                if (Oracle.StackingKey.Value.IsDown())
                {
                    DumpSink.DumpStackingFacts("hotkey");
                }

                TargetCaptureRuntime.MonitorUpdate(Time.frameCount);
                Oracle.TickArmTimeout();
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle Update failed: " + e);
            }
        }
    }

    /// <summary>Shared static state. Harmony patches are static, so this is where they meet the plugin.</summary>
    internal static class Oracle
    {
        internal static ManualLogSource Log;
        internal static ConfigEntry<KeyboardShortcut> DumpKey;
        internal static ConfigEntry<KeyboardShortcut> StackingKey;
        internal static ConfigEntry<bool> DumpOnPaste;
        internal static ConfigEntry<bool> AlwaysCaptureColliders;
        internal static ConfigEntry<bool> PatchPhysicsOverlap;
        internal static ConfigEntry<string> OutputDir;

        internal static string OutputDirectory;
        internal static int DumpCounter;

        /// <summary>Set by the hotkey; cleared by the CheckBuildConditions postfix that serves it.</summary>
        internal static bool HotkeyPending;

        private static int _armFrame = -1;

        /// <summary>True while the armed pass is running, so MatchInserter captures collider identities.</summary>
        internal static bool CaptureDetail;

        internal static bool OverlapPatchApplied;
        internal static bool CapsulePatchApplied;
        internal static bool OverlapHookEverFired;

        internal static readonly Dictionary<BuildPreview, MatchRecord> Records =
            new Dictionary<BuildPreview, MatchRecord>();

        internal static MatchRecord ActiveRecord;
        internal static MatchCall ActiveCall;
        internal static BuildTool_BlueprintPaste ActiveTool;

        internal static void ResolveOutputDirectory()
        {
            string dir = OutputDir.Value;
            if (string.IsNullOrEmpty(dir))
            {
                dir = Path.Combine(Paths.BepInExRootPath, "flab2bp-oracle");
            }

            OutputDirectory = Path.GetFullPath(dir);
            Directory.CreateDirectory(OutputDirectory);
            DumpCounter = ScanHighestExistingIndex(OutputDirectory);
        }

        private static int ScanHighestExistingIndex(string dir)
        {
            int highest = 0;
            try
            {
                Regex rx = new Regex(@"^dump-(\d+)\.json$", RegexOptions.IgnoreCase);
                foreach (string path in Directory.GetFiles(dir, "dump-*.json"))
                {
                    Match m = rx.Match(Path.GetFileName(path));
                    if (!m.Success)
                    {
                        continue;
                    }

                    int n;
                    if (int.TryParse(m.Groups[1].Value, NumberStyles.Integer, CultureInfo.InvariantCulture, out n) && n > highest)
                    {
                        highest = n;
                    }
                }
            }
            catch (Exception e)
            {
                Log.LogWarning("Could not scan " + dir + " for existing dumps: " + e.Message);
            }

            return highest;
        }

        internal static void ArmHotkey()
        {
            HotkeyPending = true;
            CaptureDetail = true;
            _armFrame = Time.frameCount;
            Log.LogMessage("flab2bp oracle armed; dumping on the next CheckBuildConditions pass.");
        }

        /// <summary>
        /// If the blueprint paste tool never runs, CheckBuildConditions never
        /// fires and the arm would hang forever. Say so out loud rather than
        /// leaving the user staring at a silent key.
        /// </summary>
        internal static void TickArmTimeout()
        {
            if (!HotkeyPending)
            {
                return;
            }

            if (Time.frameCount - _armFrame < 180)
            {
                return;
            }

            HotkeyPending = false;
            CaptureDetail = AlwaysCaptureColliders.Value;
            Log.LogWarning(
                "flab2bp oracle: armed 180 frames ago but BuildTool_BlueprintPaste.CheckBuildConditions never ran. " +
                "Is a blueprint actually on the cursor? Nothing was dumped.");
        }

        internal static bool WantDetail()
        {
            return CaptureDetail || AlwaysCaptureColliders.Value;
        }

        /// <summary>Records are keyed by BuildPreview identity, and
        /// FreeBuildPreviews throws the whole pool away on tool close, so hold
        /// nothing from a pool that is no longer the live one.</summary>
        private static BuildPreview[] _lastPool;

        private const int MaxRecords = 32768;
        private static bool _warnedRecordCap;

        internal static void NoteToolPool(BuildPreview[] pool)
        {
            if (!ReferenceEquals(pool, _lastPool))
            {
                _lastPool = pool;
                Records.Clear();
                return;
            }

            if (Records.Count <= MaxRecords)
            {
                return;
            }

            Records.Clear();
            if (!_warnedRecordCap)
            {
                _warnedRecordCap = true;
                Log.LogWarning(
                    "flab2bp oracle: MatchInserter record table passed " + MaxRecords +
                    " entries and was cleared. Dumps stay correct; previews not re-matched since " +
                    "the clear will report matchInserter: null rather than stale data.");
            }
        }

        internal static MatchRecord RecordFor(BuildPreview bp)
        {
            MatchRecord rec;
            if (!Records.TryGetValue(bp, out rec))
            {
                rec = new MatchRecord();
                Records[bp] = rec;
            }

            return rec;
        }

        internal static string NextDumpPath()
        {
            DumpCounter++;
            return Path.Combine(OutputDirectory, "dump-" + DumpCounter.ToString("D5", CultureInfo.InvariantCulture) + ".json");
        }

        internal static string NextStackingFactsPath()
        {
            string stamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture);
            return Path.Combine(OutputDirectory, "stacking-facts-" + stamp + ".json");
        }

        internal static string NextTargetCapturePath()
        {
            string stamp = DateTime.UtcNow.ToString("yyyyMMdd-HHmmss-fff", CultureInfo.InvariantCulture);
            return Path.Combine(OutputDirectory, "model40-belt-capture-" + stamp + ".json");
        }
    }
}
