using System;
using UnityEngine;
using HarmonyLib;

namespace FlabOracle
{
    /// <summary>
    /// Observes one MatchInserter call. The prefix snapshots the preview's
    /// connection fields before the game touches them; the postfix snapshots
    /// them after. Nothing in between is computed by us.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "MatchInserter")]
    internal static class MatchInserterPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance, BuildPreview bp)
        {
            try
            {
                if (bp == null)
                {
                    return;
                }

                Oracle.NoteToolPool(__instance != null ? __instance.bpPool : null);

                MatchRecord rec = Oracle.RecordFor(bp);
                rec.BeginFrame(Time.frameCount, Oracle.WantDetail());

                MatchCall call = new MatchCall();
                call.Before = PreviewConnState.From(bp);
                call.OverlapFrom = rec.Overlaps.Count;
                call.OverlapTake = 0;

                Oracle.ActiveTool = __instance;
                Oracle.ActiveCall = call;
                Oracle.ActiveRecord = rec;
            }
            catch (Exception e)
            {
                Oracle.ActiveRecord = null;
                Oracle.Log.LogError("flab2bp oracle MatchInserter prefix failed: " + e);
            }
        }

        [HarmonyPostfix]
        private static void Postfix(BuildPreview bp)
        {
            try
            {
                MatchRecord rec = Oracle.ActiveRecord;
                if (rec != null && bp != null)
                {
                    MatchCall call = Oracle.ActiveCall;
                    call.After = PreviewConnState.From(bp);
                    call.OverlapTake = rec.Overlaps.Count - call.OverlapFrom;
                    rec.Calls.Add(call);
                }
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle MatchInserter postfix failed: " + e);
            }
            finally
            {
                Oracle.ActiveRecord = null;
            }
        }
    }

    /// <summary>
    /// The hotkey dump lands here, because this is the only moment at which every
    /// preview's <c>condition</c> is the game's finished verdict for the current
    /// cursor position.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "CheckBuildConditions")]
    internal static class CheckBuildConditionsPatch
    {
        [HarmonyPrefix]
        private static void Prefix()
        {
            Oracle.ActiveRecord = null;
        }

        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance, bool __result)
        {
            Oracle.ActiveRecord = null;

            if (!Oracle.HotkeyPending)
            {
                return;
            }

            Oracle.HotkeyPending = false;
            bool detailed = Oracle.CaptureDetail;
            Oracle.CaptureDetail = Oracle.AlwaysCaptureColliders.Value;

            DumpSink.Dump(__instance, "hotkey", __result, detailed);
        }
    }

    /// <summary>
    /// The commit. Dumped twice so the pre-commit verdicts and the post-commit
    /// objIds are both on record and distinguishable.
    /// </summary>
    [HarmonyPatch(typeof(BuildTool_BlueprintPaste), "CreatePrebuilds")]
    internal static class CreatePrebuildsPatch
    {
        [HarmonyPrefix]
        private static void Prefix(BuildTool_BlueprintPaste __instance)
        {
            if (Oracle.DumpOnPaste == null || !Oracle.DumpOnPaste.Value)
            {
                return;
            }

            DumpSink.Dump(__instance, "createprebuilds-pre", null, Oracle.WantDetail());
        }

        [HarmonyPostfix]
        private static void Postfix(BuildTool_BlueprintPaste __instance)
        {
            if (Oracle.DumpOnPaste == null || !Oracle.DumpOnPaste.Value)
            {
                return;
            }

            DumpSink.Dump(__instance, "createprebuilds-post", null, Oracle.WantDetail());
        }
    }

    /// <summary>
    /// Records the raw PhysX candidate set behind MatchInserter's snap ladder.
    /// The count is the engine's return value; the identity of each collider is
    /// resolved by the game's own PlanetPhysics.GetColliderData. We invent
    /// nothing and we filter nothing.
    ///
    /// Applied manually (see OraclePlugin.TryPatchOverlapSphere) so that a
    /// missing overload or a refused patch degrades to overlapObserved=false
    /// instead of killing plugin load.
    /// </summary>
    internal static class PhysicsPatch
    {
        internal static void OverlapSphereNonAllocPostfix(
            Vector3 position,
            float radius,
            Collider[] results,
            int layerMask,
            int __result)
        {
            MatchRecord rec = Oracle.ActiveRecord;
            if (rec == null)
            {
                return;
            }

            Oracle.OverlapHookEverFired = true;

            try
            {
                OverlapObservation obs;
                obs.Center = position;
                obs.Radius = radius;
                obs.LayerMask = layerMask;
                obs.ColliderCount = __result;
                obs.ColliderFrom = rec.Colliders.Count;
                obs.ColliderTake = 0;

                if (rec.Detailed && results != null && __result > 0)
                {
                    PlanetPhysics physics = null;
                    if (Oracle.ActiveTool != null && Oracle.ActiveTool.planet != null)
                    {
                        physics = Oracle.ActiveTool.planet.physics;
                    }

                    int take = __result;
                    if (take > results.Length)
                    {
                        take = results.Length;
                    }

                    for (int i = 0; i < take; i++)
                    {
                        rec.Colliders.Add(Describe(results[i], physics));
                    }

                    obs.ColliderTake = take;
                }

                rec.Overlaps.Add(obs);
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle overlap postfix failed: " + e);
            }
        }

        private static ColliderObservation Describe(Collider col, PlanetPhysics physics)
        {
            ColliderObservation o = new ColliderObservation();
            o.HasColliderData = false;
            o.ObjId = 0;
            o.ObjType = null;
            o.Usage = null;
            o.Shape = null;
            o.Link = 0;
            o.GameObjectLayer = -1;
            o.Name = null;

            if (col == null)
            {
                return o;
            }

            try
            {
                GameObject go = col.gameObject;
                if (go != null)
                {
                    o.Name = go.name;
                    o.GameObjectLayer = go.layer;
                }
            }
            catch (Exception)
            {
                // A destroyed collider is a fact about the frame, not an error.
            }

            if (physics == null)
            {
                return o;
            }

            try
            {
                ColliderData cd;
                if (physics.GetColliderData(col, out cd))
                {
                    o.HasColliderData = true;
                    o.ObjId = cd.objId;
                    o.ObjType = cd.objType.ToString();
                    o.Usage = cd.usage.ToString();
                    o.Shape = cd.shape.ToString();
                    o.Link = cd.link;
                    o.Pos = cd.pos;
                    o.Ext = cd.ext;
                    o.Radius = cd.radius;
                    o.Rot = cd.q;
                }
            }
            catch (Exception e)
            {
                Oracle.Log.LogError("flab2bp oracle GetColliderData failed: " + e);
            }

            return o;
        }
    }
}
