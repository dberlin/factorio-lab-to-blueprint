using System.Collections.Generic;
using UnityEngine;

namespace FlabOracle
{
    /// <summary>
    /// One observation of a single <c>Physics.OverlapSphereNonAlloc</c> call made
    /// from inside <c>MatchInserter</c>. Every field is copied straight out of the
    /// call's arguments and its return value -- nothing here is recomputed.
    /// </summary>
    internal struct OverlapObservation
    {
        public Vector3 Center;
        public float Radius;
        public int LayerMask;
        public int ColliderCount;

        /// <summary>Index of the first entry in <see cref="MatchRecord.Colliders"/>.</summary>
        public int ColliderFrom;

        /// <summary>Number of entries in <see cref="MatchRecord.Colliders"/>; 0 when detail was not captured.</summary>
        public int ColliderTake;
    }

    /// <summary>
    /// What the game's own <c>PlanetPhysics.GetColliderData</c> says about one
    /// collider that PhysX returned. The mapping from collider to objId is the
    /// game's, not ours.
    /// </summary>
    internal struct ColliderObservation
    {
        public string Name;
        public int GameObjectLayer;
        public bool HasColliderData;
        public int ObjId;
        public string ObjType;
        public string Usage;
        public string Shape;
        public int Link;
        public Vector3 Pos;
        public Vector3 Ext;
        public float Radius;
        public Quaternion Rot;
    }

    /// <summary>Snapshot of the connection fields of a BuildPreview at one instant.</summary>
    internal struct PreviewConnState
    {
        public int InputObjId;
        public int InputFromSlot;
        public int InputToSlot;
        public int InputOffset;
        public int OutputObjId;
        public int OutputFromSlot;
        public int OutputToSlot;
        public int OutputOffset;
        public bool HasInput;
        public bool HasOutput;
        public Vector3 Lpos;
        public Vector3 Lpos2;
        public Quaternion Lrot;
        public Quaternion Lrot2;
        public int Condition;

        public static PreviewConnState From(BuildPreview bp)
        {
            PreviewConnState s;
            s.InputObjId = bp.inputObjId;
            s.InputFromSlot = bp.inputFromSlot;
            s.InputToSlot = bp.inputToSlot;
            s.InputOffset = bp.inputOffset;
            s.OutputObjId = bp.outputObjId;
            s.OutputFromSlot = bp.outputFromSlot;
            s.OutputToSlot = bp.outputToSlot;
            s.OutputOffset = bp.outputOffset;
            s.HasInput = bp.input != null;
            s.HasOutput = bp.output != null;
            s.Lpos = bp.lpos;
            s.Lpos2 = bp.lpos2;
            s.Lrot = bp.lrot;
            s.Lrot2 = bp.lrot2;
            s.Condition = (int)bp.condition;
            return s;
        }
    }

    /// <summary>
    /// One <c>MatchInserter(bp)</c> call. CheckBuildConditions calls it up to
    /// twice per preview per pass -- once with the input side cleared and once
    /// with the output side cleared -- and it is called again later in the same
    /// pass for multi-level previews, so calls are accumulated, never replaced.
    /// </summary>
    internal struct MatchCall
    {
        public PreviewConnState Before;
        public PreviewConnState After;

        /// <summary>Index of the first entry in <see cref="MatchRecord.Overlaps"/>.</summary>
        public int OverlapFrom;

        public int OverlapTake;
    }

    /// <summary>
    /// Everything observed for one BuildPreview during one frame. Reused across
    /// frames so the steady state allocates nothing.
    /// </summary>
    internal sealed class MatchRecord
    {
        public int Frame = -1;
        public bool Detailed;
        public readonly List<MatchCall> Calls = new List<MatchCall>(4);
        public readonly List<OverlapObservation> Overlaps = new List<OverlapObservation>(8);
        public readonly List<ColliderObservation> Colliders = new List<ColliderObservation>(64);

        /// <summary>Starts a new frame's accumulation, or joins the frame already in progress.</summary>
        public void BeginFrame(int frame, bool detailed)
        {
            if (Frame != frame)
            {
                Frame = frame;
                Detailed = detailed;
                Calls.Clear();
                Overlaps.Clear();
                Colliders.Clear();
            }
            else if (detailed)
            {
                Detailed = true;
            }
        }
    }
}
