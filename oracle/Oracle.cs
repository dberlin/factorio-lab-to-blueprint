using System;
using System.Collections.Generic;
using UnityEngine;

namespace SnapOracle
{
    /// <summary>
    /// <c>BuildTool_BlueprintPaste.MatchInserter</c>, transcribed line for line from
    /// the decompiled shipped assembly and run on a caller-supplied candidate set.
    ///
    /// <para>
    /// WHAT THIS IS AN ORACLE FOR, AND WHAT IT IS NOT.  The game finds its snap
    /// candidates with <c>Physics.OverlapSphereNonAlloc</c> against the live PhysX
    /// scene, then walks from each collider back to an entity, a prebuild, or a
    /// <c>BuildPreviewModel</c>.  None of that exists outside the running game, and
    /// any collider set synthesised here would be OUR model of the scene -- the very
    /// thing under test.  So the candidate set is an INPUT: the caller says what the
    /// query returned, and this class runs the game's arithmetic over it.
    /// </para>
    ///
    /// <para>
    /// A disagreement found this way is a transcription bug in our port of the
    /// ladder, and that is worth finding.  Agreement proves the port faithful and
    /// proves NOTHING about whether we predict the right candidate set; that needs
    /// the real scene.
    /// </para>
    ///
    /// <para>
    /// The decompiler's own names are kept -- <c>num4</c>, <c>flag3</c>,
    /// <c>vector4</c> -- so this file diffs line by line against
    /// <c>BuildTool_BlueprintPaste.cs</c> lines 1462-1746.  Four substitutions were
    /// unavoidable and each is marked <c>// HARNESS:</c> where it occurs:
    /// the sphere query, <c>GetColliderData</c>, the three <c>BuildTool</c> lookups
    /// (<c>GetObjectPose</c>, <c>GetLocalSlots</c>, <c>ObjectIsBelt</c>), and the two
    /// <c>Quaternion</c> members that are native thunks (see <see cref="Quat"/>).
    /// Everything else -- the dots, the thresholds, the ordering, the branch
    /// structure -- is the shipped code.
    /// </para>
    /// </summary>
    internal sealed class Oracle
    {
        private readonly List<Candidate> _tmp_cols;
        private readonly Dictionary<int, Candidate> _byObjId = new Dictionary<int, Candidate>();
        private readonly Dictionary<BuildPreview, int> _previewIndex = new Dictionary<BuildPreview, int>();
        private readonly List<CandScore> _scores = new List<CandScore>();

        // HARNESS: verbatim from BuildTool_BlueprintPaste.cs line 104, with
        // Quaternion.Euler swapped for Quat.Euler (see Quat).
        private readonly Pose[] belt_slots = new Pose[4]
        {
            new Pose(new Vector3(0f, 0f, 0f), Quaternion.identity),
            new Pose(new Vector3(0f, 0f, 0f), Quat.Euler(0f, 90f, 0f)),
            new Pose(new Vector3(0f, 0f, 0f), Quat.Euler(0f, 180f, 0f)),
            new Pose(new Vector3(0f, 0f, 0f), Quat.Euler(0f, -90f, 0f))
        };

        private static readonly Pose[] EmptyPoseArr = new Pose[0];

        internal Oracle(Case c)
        {
            this._tmp_cols = c.Candidates;
            for (int i = 0; i < c.Candidates.Count; i++)
            {
                Candidate cand = c.Candidates[i];
                if (cand.Kind == "entity" || cand.Kind == "prebuild")
                {
                    this._byObjId[cand.ObjId] = cand;
                }
                if (cand.Kind == "preview")
                {
                    this._previewIndex[Preview(cand)] = i;
                }
            }
        }

        /// <summary>The <c>BuildPreview</c> a preview candidate stands for, made once.</summary>
        private readonly Dictionary<Candidate, BuildPreview> _previews = new Dictionary<Candidate, BuildPreview>();

        internal BuildPreview Preview(Candidate cand)
        {
            if (!this._previews.TryGetValue(cand, out BuildPreview bp))
            {
                bp = new BuildPreview();
                bp.lpos = Json.Vec(cand.BpPos ?? cand.Pos);
                bp.lrot = cand.BpRot != null ? Json.Quat(cand.BpRot) : Rotation(cand);
                bp.desc = new PrefabDesc();
                bp.desc.slotPoses = Slots(cand);
                this._previews[cand] = bp;
            }
            return bp;
        }

        internal int IndexOfPreview(BuildPreview bp)
        {
            if (bp == null)
            {
                return -1;
            }
            return this._previewIndex.TryGetValue(bp, out int i) ? i : -1;
        }

        /// <summary>A candidate's rotation, from its quaternion or from its yaw.</summary>
        internal static Quaternion Rotation(Candidate cand)
        {
            if (cand.Rot != null)
            {
                return Json.Quat(cand.Rot);
            }
            return Quat.Euler(0f, cand.Yaw ?? 0f, 0f);
        }

        /// <summary>
        /// Built poses per slot table, keyed on the list INSTANCE so a table shared
        /// by a sweep's thousands of candidates is converted once.  <c>List&lt;T&gt;</c>
        /// does not override equality, so the default comparer is reference identity
        /// -- which is what is wanted: two tables with equal contents are still two
        /// tables, and nothing here depends on collapsing them.
        /// </summary>
        private static readonly Dictionary<List<SlotPoseDto>, Pose[]> SlotCache
            = new Dictionary<List<SlotPoseDto>, Pose[]>();

        private static Pose[] Slots(Candidate cand)
        {
            if (SlotCache.TryGetValue(cand.SlotPoses, out Pose[] cached))
            {
                return cached;
            }
            Pose[] arr = new Pose[cand.SlotPoses.Count];
            for (int i = 0; i < arr.Length; i++)
            {
                arr[i] = cand.SlotPoses[i].ToPose();
            }
            SlotCache[cand.SlotPoses] = arr;
            return arr;
        }

        // ---- HARNESS: the three BuildTool lookups, reading the supplied candidate
        // ---- set instead of factory.entityPool / factory.prebuildPool / LDB.models.
        // ---- Their signatures and their handling of the id's sign are BuildTool.cs
        // ---- lines 615, 726 and 835 unchanged.

        private Candidate Lookup(int objId)
        {
            if (objId == 0)
            {
                return null;
            }
            return this._byObjId.TryGetValue(Math.Abs(objId), out Candidate c) ? c : null;
        }

        internal Pose GetObjectPose(int objId)
        {
            Candidate c = this.Lookup(objId);
            if (c == null)
            {
                return Pose.identity;
            }
            return new Pose(Json.Vec(c.Pos), Rotation(c));
        }

        internal Pose[] GetLocalSlots(int objId)
        {
            Candidate c = this.Lookup(objId);
            return c == null ? EmptyPoseArr : Slots(c);
        }

        internal bool ObjectIsBelt(int objId)
        {
            Candidate c = this.Lookup(objId);
            return c != null && c.IsBelt;
        }

        // HARNESS: planet.physics.GetColliderData. A candidate declares what the
        // physics layer would have said about it; "other" is a collider the query
        // returned that resolves to nothing the ladder can use.
        private static bool GetColliderData(Candidate col, out ColliderData cd)
        {
            cd = default(ColliderData);
            switch (col.Kind)
            {
                case "entity":
                    cd.idType = Pack(EObjectType.None, col.ObjId);
                    return true;
                case "prebuild":
                    cd.idType = Pack(EObjectType.Prebuild, col.ObjId);
                    return true;
                case "othertype":
                    cd.idType = Pack(EObjectType.Entity, col.ObjId);
                    return true;
                default:
                    return false;
            }
        }

        /// <summary>
        /// The real <see cref="ColliderData"/> struct, filled the way the physics
        /// layer fills it: <c>objId</c> and <c>objType</c> are read-only views onto
        /// the packed <c>idType</c> word, so this is the game's own bit layout
        /// (<c>ColliderData.cs</c>) rather than a stand-in struct.
        /// </summary>
        private static int Pack(EObjectType objType, int objId)
        {
            if (objId < 0 || objId > 0xFFFFFF)
            {
                throw new ArgumentOutOfRangeException(nameof(objId), objId, "objId is a 24-bit field");
            }
            return objId | (((int)objType & 7) << 26);
        }

        // HARNESS: BuildTool._tmp_cols[i].gameObject.layer. A BuildPreviewModel sits
        // on layer 18; nothing else the ladder looks at does.
        private static int LayerOf(Candidate col)
        {
            return col.Kind == "preview" ? 18 : 0;
        }

        /// <summary>
        /// The transcription.  Compare against <c>BuildTool_BlueprintPaste.cs</c>
        /// lines 1462-1746 (repo-cited line numbers map onto that file at a constant
        /// offset of 143582).
        /// </summary>
        internal void MatchInserter(BuildPreview bp, Verdict verdict)
        {
            bool flag = bp.output == null && bp.outputObjId == 0;
            bool flag2 = bp.input == null && bp.inputObjId == 0;
            if (flag | flag2)
            {
                do
                {
                    Step step = new Step { Side = flag ? "output" : "input" };
                    verdict.Trace.Add(step);
                    this._scores.Clear();

                    Vector3 vector = (flag ? bp.lpos2 : bp.lpos);
                    Vector3 vector2 = (flag ? bp.lpos : bp.lpos2);
                    Vector3 lhs = (flag ? (bp.lpos2 - bp.lpos).normalized : (bp.lpos - bp.lpos2).normalized);
                    Quaternion obj = (flag ? bp.lrot2 : bp.lrot);
                    Vector3 vector3 = Maths.Forward(flag ? bp.lrot : bp.lrot2);
                    Vector3 vector4 = vector;
                    Quaternion quaternion = obj;
                    int num = 0;
                    BuildPreview buildPreview = null;
                    int num2 = 0;
                    int num3 = 0;
                    bool flag3 = false;
                    float num4 = 99f;
                    int num5 = 0;
                    BuildPreview buildPreview2 = null;
                    int num6 = 0;
                    bool flag4 = false;
                    // HARNESS: `int layerMask = 393216;` and the OverlapSphereNonAlloc
                    // that used it are the PhysX query. The caller supplies its result.
                    int num7 = this._tmp_cols.Count;
                    if (num7 > 0)
                    {
                        for (int i = 0; i < num7; i++)
                        {
                            float num8 = 100f;
                            int num9 = 0;
                            int num10 = 0;
                            bool flag5 = false;
                            BuildPreview buildPreview3 = null;
                            if (GetColliderData(this._tmp_cols[i], out ColliderData cd))
                            {
                                if (cd.objType == EObjectType.None || cd.objType == EObjectType.Prebuild)
                                {
                                    num10 = 0;
                                    num9 = ((cd.objType == EObjectType.None) ? cd.objId : (-cd.objId));
                                    flag5 = this.ObjectIsBelt(num9);
                                    if (flag5)
                                    {
                                        Pose objectPose = this.GetObjectPose(num9);
                                        Pose[] array = this.belt_slots;
                                        for (int j = 0; j < array.Length; j++)
                                        {
                                            Vector3 vector5 = objectPose.position + (objectPose.rotation * array[j].position);
                                            Vector3 rhs = objectPose.rotation * array[j].rotation * new Vector3(0f, 0f, -1f);
                                            float num11 = Vector3.Dot(lhs, rhs);
                                            float num12 = Vector3.Dot((vector5 - vector2).normalized, rhs);
                                            if (num11 > 0.9f && num12 > 0.8f)
                                            {
                                                num8 = (objectPose.position - vector).sqrMagnitude;
                                                num10 = j;
                                                break;
                                            }
                                        }
                                    }
                                    else
                                    {
                                        Pose objectPose2 = this.GetObjectPose(num9);
                                        Pose[] localSlots = this.GetLocalSlots(num9);
                                        for (int k = 0; k < localSlots.Length; k++)
                                        {
                                            Vector3 vector6 = objectPose2.position + (objectPose2.rotation * localSlots[k].position);
                                            Vector3 rhs2 = objectPose2.rotation * localSlots[k].rotation * new Vector3(0f, 0f, -1f);
                                            float num13 = Vector3.Dot(lhs, rhs2);
                                            float num14 = Vector3.Dot((vector6 - vector2).normalized, rhs2);
                                            if (num13 > 0.9702957f && num14 > 0.9702957f)
                                            {
                                                float sqrMagnitude = (vector6 - vector).sqrMagnitude;
                                                if (sqrMagnitude < num8)
                                                {
                                                    num8 = sqrMagnitude;
                                                    num10 = k;
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            else if (LayerOf(this._tmp_cols[i]) == 18)
                            {
                                // HARNESS: GetComponent<BuildPreviewModel>() -- the
                                // candidate IS the component, and `pose` below is its
                                // transform, supplied as `pos` / `rot`.
                                Candidate component = this._tmp_cols[i];
                                if (component != null)
                                {
                                    Pose[] slotPoses = this.Preview(component).desc.slotPoses;
                                    if (slotPoses != null && slotPoses.Length != 0)
                                    {
                                        Pose pose = new Pose(Json.Vec(component.Pos), Rotation(component));
                                        for (int l = 0; l < slotPoses.Length; l++)
                                        {
                                            Vector3 vector7 = pose.position + (pose.rotation * slotPoses[l].position);
                                            Vector3 rhs3 = pose.rotation * slotPoses[l].rotation * new Vector3(0f, 0f, -1f);
                                            float num15 = Vector3.Dot(lhs, rhs3);
                                            float num16 = Vector3.Dot((vector7 - vector2).normalized, rhs3);
                                            if (num15 > 0.9702957f && num16 > 0.9702957f)
                                            {
                                                float sqrMagnitude2 = (vector7 - vector).sqrMagnitude;
                                                if (sqrMagnitude2 < num8)
                                                {
                                                    num8 = sqrMagnitude2;
                                                    num10 = l;
                                                    buildPreview3 = this.Preview(component);
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                            this._scores.Add(new CandScore
                            {
                                Index = i,
                                Num8 = num8,
                                Num9 = num9,
                                Num10 = num10,
                                Flag5 = flag5
                            });
                            if (num8 < num4)
                            {
                                num4 = num8;
                                num5 = num9;
                                buildPreview2 = buildPreview3;
                                num6 = num10;
                                flag4 = flag5;
                            }
                        }
                    }
                    step.Scores.AddRange(this._scores);
                    if (num4 < 6f && (num5 != 0 || buildPreview2 != null))
                    {
                        if (flag4)
                        {
                            if (num5 > 0)
                            {
                                Pose objectPose3 = this.GetObjectPose(num5);
                                Pose[] array2 = this.belt_slots;
                                vector4 = objectPose3.position + (objectPose3.rotation * array2[num6].position);
                                quaternion = objectPose3.rotation * array2[num6].rotation;
                                num = num5;
                                num2 = -1;
                                num3 = 0;
                                flag3 = true;
                                Vector3 vector8 = vector2 - vector4;
                                Vector3 lhs2 = -vector8;
                                // HARNESS: entityPool[num5].beltId -> cargoTraffic.beltPool[beltId]
                                // -> cargoTraffic.GetCargoPath(segPathId). A cargo path only exists
                                // inside a running factory, so the caller supplies it.
                                BeltPathDto cargoPath = this.Lookup(num5).Belt;
                                if (cargoPath == null)
                                {
                                    throw new InvalidOperationException(
                                        $"candidate {num5} is a built belt and the ladder needs its cargo path; supply `belt`");
                                }
                                int num17 = cargoPath.SegIndex;
                                int num18 = cargoPath.SegIndex + cargoPath.SegLength;
                                int num19 = cargoPath.SegIndex + cargoPath.SegPivotOffset;
                                if (num17 < 4)
                                {
                                    num17 = 4;
                                }
                                if (num17 > cargoPath.PathLength - 5 - 1)
                                {
                                    num17 = cargoPath.PathLength - 5 - 1;
                                }
                                if (num18 < 4)
                                {
                                    num18 = 4;
                                }
                                if (num18 > cargoPath.PathLength - 5 - 1)
                                {
                                    num18 = cargoPath.PathLength - 5 - 1;
                                }
                                if (num19 < 4)
                                {
                                    num19 = 4;
                                }
                                if (num19 > cargoPath.PathLength - 5 - 1)
                                {
                                    num19 = cargoPath.PathLength - 5 - 1;
                                }
                                for (int m = num17; m < num18; m++)
                                {
                                    float num20 = Vector3.Dot(lhs2, vector3);
                                    Vector3 vector9 = Json.Vec(cargoPath.PointPos[m]);
                                    Vector3 vector10 = Json.Vec(cargoPath.PointPos[m + 1]);
                                    Vector3 point = vector2 + (vector3 * num20);
                                    float num21 = NGPT.Kit.ClosestPoint2Straight(vector9, vector10, point);
                                    if (num21 >= 0f && num21 <= 1f)
                                    {
                                        vector4 = vector9 + ((vector10 - vector9) * num21);
                                        vector4 -= vector4.normalized * 0.15f;
                                        quaternion = Quat.Slerp(Json.Quat(cargoPath.PointRot[m]), Json.Quat(cargoPath.PointRot[m + 1]), num21);
                                        Quaternion identity = Quaternion.identity;
                                        Vector3 zero = Vector3.zero;
                                        identity = quaternion * Quat.Euler(0f, 90f, 0f);
                                        zero = Maths.Forward(identity);
                                        if (Vector3.Angle(vector8, zero) < 40f)
                                        {
                                            quaternion = identity;
                                        }
                                        identity = quaternion * Quat.Euler(0f, 180f, 0f);
                                        zero = Maths.Forward(identity);
                                        if (Vector3.Angle(vector8, zero) < 40f)
                                        {
                                            quaternion = identity;
                                        }
                                        identity = quaternion * Quat.Euler(0f, -90f, 0f);
                                        zero = Maths.Forward(identity);
                                        if (Vector3.Angle(vector8, zero) < 40f)
                                        {
                                            quaternion = identity;
                                        }
                                        num3 = m - num19;
                                    }
                                }
                            }
                            else if (num5 >= 0)
                            {
                                // The game's own empty branch. num5 < 0 -- a PREBUILT belt --
                                // reaches neither arm, so flag3 stays false and the end does
                                // not snap at all. That is shipped behaviour, not an omission.
                            }
                        }
                        else
                        {
                            Pose pose2 = default(Pose);
                            Pose[] array3 = null;
                            if (num5 != 0)
                            {
                                pose2 = this.GetObjectPose(num5);
                                array3 = this.GetLocalSlots(num5);
                            }
                            else if (buildPreview2 != null)
                            {
                                pose2 = new Pose(buildPreview2.lpos, buildPreview2.lrot);
                                array3 = buildPreview2.desc.slotPoses;
                            }
                            if (array3 != null && array3.Length != 0)
                            {
                                vector4 = pose2.position + (pose2.rotation * array3[num6].position);
                                quaternion = pose2.rotation * array3[num6].rotation;
                                num = num5;
                                buildPreview = buildPreview2;
                                num2 = num6;
                                num3 = 0;
                                flag3 = true;
                            }
                        }
                    }
                    step.Num4 = num4;
                    step.Num5 = num5;
                    step.Num6 = num6;
                    step.Preview = this.IndexOfPreview(buildPreview2);
                    step.Flag4 = flag4;
                    step.Flag3 = flag3;
                    if (!flag3)
                    {
                        break;
                    }
                    if (flag)
                    {
                        bp.lpos2 = vector4;
                        bp.lrot2 = quaternion * Quat.Euler(0f, 180f, 0f);
                        bp.output = buildPreview;
                        if (bp.output == null)
                        {
                            bp.outputObjId = num;
                        }
                        bp.outputToSlot = num2;
                        bp.outputFromSlot = 0;
                        bp.outputOffset = num3;
                        flag = false;
                        continue;
                    }
                    bp.lpos = vector4;
                    bp.lrot = quaternion;
                    bp.input = buildPreview;
                    if (bp.input == null)
                    {
                        bp.inputObjId = num;
                    }
                    bp.inputFromSlot = num2;
                    bp.inputToSlot = 1;
                    bp.inputOffset = num3;
                    flag2 = false;
                    break;
                }
                while (flag2);
            }
            if (flag | flag2)
            {
                bp.condition = EBuildCondition.NeedConn;
            }
            else
            {
                bp.condition = EBuildCondition.Ok;
            }
        }
    }
}
