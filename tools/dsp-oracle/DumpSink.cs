using System;
using System.IO;
using UnityEngine;

namespace FlabOracle
{
    /// <summary>
    /// The one place that turns a serialised dump into a file on disk and a line
    /// in the BepInEx console. Kept apart from <see cref="Dumper"/> so that the
    /// serialiser itself has no BepInEx or Unity-player dependency and can be
    /// exercised outside the game (see the SerializerCheck harness).
    /// </summary>
    internal static class DumpSink
    {
        internal static void Dump(BuildTool_BlueprintPaste tool, string trigger, bool? checkResult, bool detailed)
        {
            try
            {
                DumpContext ctx;
                ctx.OverlapPatchApplied = Oracle.OverlapPatchApplied;
                ctx.OverlapHookEverFired = Oracle.OverlapHookEverFired;
                ctx.UnityFrame = Time.frameCount;
                ctx.Records = Oracle.Records;

                string json = Dumper.Serialize(tool, trigger, checkResult, detailed, ctx);
                if (json == null)
                {
                    Oracle.Log.LogWarning(
                        "flab2bp oracle: no preview pool for trigger " + trigger + "; nothing dumped.");
                    return;
                }

                string path = Oracle.NextDumpPath();
                File.WriteAllText(path, json);
                Oracle.Log.LogMessage("flab2bp oracle wrote " + path + "  (trigger=" + trigger + ")");
            }
            catch (Exception e)
            {
                // A field-name mistake must cost a log line, never the user's game.
                Oracle.Log.LogError("flab2bp oracle dump (" + trigger + ") failed: " + e);
            }
        }

        /// <summary>
        /// The sorter cargo-stacking and Automatic Piler dump. Independent of the
        /// paste tool: it reads LDB, the game history and the live component pools,
        /// so it works from any screen (and says so in the file when there is no
        /// save loaded and only the LDB half is available).
        /// </summary>
        internal static void DumpStackingFacts(string trigger)
        {
            try
            {
                string json = StackingFacts.Serialize(trigger);
                string path = Oracle.NextStackingFactsPath();
                File.WriteAllText(path, json);
                Oracle.Log.LogMessage("flab2bp oracle wrote stacking facts " + path);
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle stacking-facts dump failed: " + e);
            }
        }

        internal static void DumpTargetCapture(TargetCaptureSession capture, string trigger, bool? checkResult)
        {
            try
            {
                string json = capture.Serialize(
                    trigger,
                    checkResult,
                    Time.frameCount,
                    Oracle.OverlapPatchApplied,
                    Oracle.CapsulePatchApplied);
                string path = Oracle.NextTargetCapturePath();
                File.WriteAllText(path, json);
                Oracle.Log.LogMessage("flab2bp oracle wrote automatic model40 belt capture " + path);
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle automatic model40 belt capture failed: " + e);
            }
        }
    }
}
