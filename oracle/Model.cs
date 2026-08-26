using System.Collections.Generic;
using UnityEngine;

namespace SnapOracle
{
    /// <summary>
    /// The wire format between the Python driver and the transcribed ladder.
    ///
    /// <para>
    /// Vectors are <c>[x, y, z]</c> and rotations <c>[x, y, z, w]</c>, both in Unity
    /// world units and Unity axes (<c>+y</c> up, <c>+z</c> forward) -- NOT this
    /// project's tile grid.  Converting is the driver's job, and doing it there
    /// keeps the transcription free of anything that is ours.
    /// </para>
    /// </summary>
    internal sealed class Request
    {
        public List<Case> Cases { get; set; } = new List<Case>();
    }

    /// <summary>One call to <c>MatchInserter</c>, with its candidate set supplied.</summary>
    internal sealed class Case
    {
        public string Name { get; set; } = "";

        /// <summary>The sorter's input (first) end, as the blueprint carries it.</summary>
        public float[] Lpos { get; set; }

        public float[] Lrot { get; set; }

        /// <summary>The sorter's output (second) end, as the blueprint carries it.</summary>
        public float[] Lpos2 { get; set; }

        public float[] Lrot2 { get; set; }

        /// <summary>Already-known ends, which the ladder leaves alone.</summary>
        public int InputObjId { get; set; }

        public int OutputObjId { get; set; }

        /// <summary>Index into <see cref="Candidates"/>, or -1 for "no preview yet".</summary>
        public int InputPreview { get; set; } = -1;

        public int OutputPreview { get; set; } = -1;

        /// <summary>
        /// What <c>Physics.OverlapSphereNonAlloc</c> WOULD have returned, in the
        /// order it would have returned it.
        ///
        /// <para>
        /// This is the input the harness cannot compute for itself and does not try
        /// to: see the note on <see cref="Oracle.MatchInserter"/>.  Order matters --
        /// the ladder's <c>num8 &lt; num4</c> keeps the FIRST of two candidates that
        /// tie, so a driver that shuffles this list is asking a different question.
        /// </para>
        /// </summary>
        public List<Candidate> Candidates { get; set; } = new List<Candidate>();
    }

    /// <summary>One collider the sphere query returned, and what lies behind it.</summary>
    internal sealed class Candidate
    {
        /// <summary>
        /// <c>"entity"</c> and <c>"prebuild"</c> answer <c>GetColliderData</c> with
        /// <c>EObjectType.None</c> and <c>EObjectType.Prebuild</c>; <c>"preview"</c>
        /// answers it with false and sits on layer 18 instead, which is what every
        /// other building of the same paste looks like.  <c>"other"</c> answers
        /// neither and is how a collider the ladder must ignore is expressed.
        /// </summary>
        public string Kind { get; set; } = "entity";

        /// <summary>
        /// <c>cd.objId</c>.  Always POSITIVE here; the ladder itself negates it for a
        /// prebuild, exactly as the game does.
        /// </summary>
        public int ObjId { get; set; }

        public bool IsBelt { get; set; }

        /// <summary>
        /// The object's own pose.  For an entity or prebuild this is what
        /// <c>GetObjectPose</c> returns; for a preview it is the preview model
        /// transform's <c>localPosition</c> / <c>localRotation</c>.
        /// </summary>
        public float[] Pos { get; set; }

        public float[] Rot { get; set; }

        /// <summary>
        /// A preview's <c>buildPreview.lpos</c> / <c>.lrot</c>, when they are not
        /// its model transform's.
        ///
        /// <para>
        /// The ladder reads a preview's pose from TWO places -- the collider loop
        /// takes <c>component.trans.localPosition</c>, and the snap 130 lines later
        /// takes <c>buildPreview2.lpos</c>.  During a paste they agree, and these
        /// default to <see cref="Pos"/> / <see cref="Rot"/> so a caller need not say
        /// so twice; they exist because collapsing two reads into one would have
        /// been the harness deciding something the game does not.
        /// </para>
        /// </summary>
        public float[] BpPos { get; set; }

        public float[] BpRot { get; set; }

        /// <summary>
        /// <c>PrefabDesc.slotPoses</c>, in the object's own frame.  For an entity or
        /// prebuild this is what <c>GetLocalSlots</c> returns; for a preview it is
        /// <c>buildPreview.desc.slotPoses</c>.  The two are the same array in the
        /// game and the ladder reaches them by two different routes.
        /// </summary>
        public List<SlotPoseDto> SlotPoses { get; set; } = new List<SlotPoseDto>();

        /// <summary>Set only on a BUILT belt entity; the branch it feeds needs a live path.</summary>
        public BeltPathDto Belt { get; set; }
    }

    internal sealed class SlotPoseDto
    {
        public float[] Pos { get; set; }

        public float[] Rot { get; set; }

        internal Pose ToPose()
        {
            return new Pose(Json.Vec(this.Pos), Json.Quat(this.Rot));
        }
    }

    /// <summary>
    /// The <c>BeltComponent</c> and <c>CargoPath</c> fields the belt branch reads.
    /// Supplied, like the candidate set, rather than discovered: a cargo path only
    /// exists inside a running factory.
    /// </summary>
    internal sealed class BeltPathDto
    {
        public int SegIndex { get; set; }

        public int SegLength { get; set; }

        public int SegPivotOffset { get; set; }

        public int PathLength { get; set; }

        public List<float[]> PointPos { get; set; } = new List<float[]>();

        public List<float[]> PointRot { get; set; } = new List<float[]>();
    }

    /// <summary>What the ladder decided, plus enough of its working to diff it.</summary>
    internal sealed class Verdict
    {
        public string Name { get; set; } = "";

        public string Condition { get; set; } = "";

        public float[] Lpos { get; set; }

        public float[] Lrot { get; set; }

        public float[] Lpos2 { get; set; }

        public float[] Lrot2 { get; set; }

        public int InputObjId { get; set; }

        public int InputPreview { get; set; } = -1;

        public int InputFromSlot { get; set; }

        public int InputToSlot { get; set; }

        public int InputOffset { get; set; }

        public int OutputObjId { get; set; }

        public int OutputPreview { get; set; } = -1;

        public int OutputFromSlot { get; set; }

        public int OutputToSlot { get; set; }

        public int OutputOffset { get; set; }

        public List<Step> Trace { get; set; } = new List<Step>();

        public string Error { get; set; }
    }

    /// <summary>One turn of the ladder's <c>do { } while (flag2)</c>, as it happened.</summary>
    internal sealed class Step
    {
        /// <summary>Which end this turn was resolving: the <c>flag</c> branch or the <c>flag2</c> one.</summary>
        public string Side { get; set; } = "";

        /// <summary>The winning squared distance, <c>num4</c>. 99 means nothing scored.</summary>
        public float Num4 { get; set; }

        /// <summary>The winning object id, <c>num5</c>; signed the way the ladder signs it.</summary>
        public int Num5 { get; set; }

        /// <summary>The winning slot index, <c>num6</c>.</summary>
        public int Num6 { get; set; }

        /// <summary>The winning preview, as an index into the case's candidate list.</summary>
        public int Preview { get; set; } = -1;

        /// <summary>Did the winner come out of the belt branch? <c>flag4</c>.</summary>
        public bool Flag4 { get; set; }

        /// <summary>Did the turn snap anything at all? <c>flag3</c>.</summary>
        public bool Flag3 { get; set; }

        /// <summary>Per-candidate scores, in the order the sphere query gave them.</summary>
        public List<CandScore> Scores { get; set; } = new List<CandScore>();
    }

    /// <summary>What one candidate scored -- <c>num8</c>, <c>num9</c>, <c>num10</c>.</summary>
    internal sealed class CandScore
    {
        public int Index { get; set; }

        public float Num8 { get; set; }

        public int Num9 { get; set; }

        public int Num10 { get; set; }

        public bool Flag5 { get; set; }
    }
}
