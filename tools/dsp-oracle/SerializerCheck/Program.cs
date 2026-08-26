using System;
using System.Collections.Generic;
using System.IO;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using UnityEngine;

namespace FlabOracle.Check
{
    /// <summary>
    /// Exercises <see cref="Dumper.Serialize"/> against real game types built by
    /// hand, then parses the result with a strict JSON reader and checks that the
    /// floats came back bit-for-bit. Catches unbalanced object/array nesting,
    /// bad escaping and lossy float formatting without needing to run the game.
    /// </summary>
    internal static class Program
    {
        private const string ManagedDir = "/home/dannyb/Dyson Sphere Program/DSPGAME_Data/Managed/";

        private static int _failures;

        private static int Main(string[] args)
        {
            string managed = args.Length > 0 ? args[0] : ManagedDir;
            AppDomain.CurrentDomain.AssemblyResolve += (s, a) =>
            {
                string name = new AssemblyName(a.Name).Name;
                string path = Path.Combine(managed, name + ".dll");
                return File.Exists(path) ? Assembly.LoadFrom(path) : null;
            };

            string json = BuildAndSerialize();
            Console.WriteLine("serialised " + json.Length + " bytes");

            string sampleOut = Environment.GetEnvironmentVariable("FLAB_ORACLE_SAMPLE_OUT");
            if (!string.IsNullOrEmpty(sampleOut))
            {
                File.WriteAllText(sampleOut, json);
                Console.WriteLine("wrote sample to " + sampleOut);
            }

            JsonDocument doc;
            try
            {
                doc = JsonDocument.Parse(json);
            }
            catch (JsonException e)
            {
                Console.WriteLine("FAIL: output is not valid JSON: " + e.Message);
                Console.WriteLine(Excerpt(json, e.BytePositionInLine.HasValue ? (int)e.BytePositionInLine.Value : 0));
                return 1;
            }

            JsonElement root = doc.RootElement;
            Check("schema", root.GetProperty("schema").GetString() == "flab2bp-oracle/1");
            Check("trigger", root.GetProperty("trigger").GetString() == "hotkey");
            Check("previewCount", root.GetProperty("previewCount").GetInt32() == 3);
            Check("checkBuildConditionsResult", root.GetProperty("checkBuildConditionsResult").GetBoolean());

            JsonElement previews = root.GetProperty("previews");
            Check("previews length", previews.GetArrayLength() == 3);

            JsonElement p0 = previews[0];
            Check("p0 condition value", p0.GetProperty("condition").GetInt32() == 0);
            Check("p0 condition name", p0.GetProperty("conditionName").GetString() == "Ok");
            Check("p0 conditionText tolerated", p0.GetProperty("conditionText").ValueKind == JsonValueKind.Null
                || p0.GetProperty("conditionText").ValueKind == JsonValueKind.String);

            JsonElement p1 = previews[1];
            Check("p1 condition value", p1.GetProperty("condition").GetInt32() == 54);
            Check("p1 condition name", p1.GetProperty("conditionName").GetString() == "ErrorInserterData");
            Check("p1 hasInput", p1.GetProperty("hasInput").GetBoolean());
            Check("p1 inputPreviewIndex", p1.GetProperty("inputPreviewIndex").GetInt32() == 0);
            Check("p1 outputPreviewIndex null", p1.GetProperty("outputPreviewIndex").ValueKind == JsonValueKind.Null);

            // Sub-tile geometry must survive the round trip exactly. This is the
            // whole reason the writer uses G9 rather than a default ToString.
            CheckVector3("p1 lpos", p1.GetProperty("lpos"), TrickyPos);
            CheckVector3("p1 lpos2", p1.GetProperty("lpos2"), TrickyPos2);
            CheckQuaternion("p1 lrot", p1.GetProperty("lrot"), TrickyRot);

            JsonElement mi = p1.GetProperty("matchInserter");
            Check("p1 matchInserter present", mi.ValueKind == JsonValueKind.Object);
            Check("p1 matchInserter callCount", mi.GetProperty("callCount").GetInt32() == 2);
            Check("p1 matchInserter calls", mi.GetProperty("calls").GetArrayLength() == 2);

            JsonElement call0 = mi.GetProperty("calls")[0];
            JsonElement q0 = call0.GetProperty("overlapQueries");
            Check("call0 one overlap query", q0.GetArrayLength() == 1);
            Check("call0 colliderCount", q0[0].GetProperty("colliderCount").GetInt32() == 7);
            Check("call0 layerMask", q0[0].GetProperty("layerMask").GetInt32() == 393216);
            Check("call0 radius", q0[0].GetProperty("radius").GetSingle() == 0.8f);
            Check("call0 colliders", q0[0].GetProperty("colliders").GetArrayLength() == 2);
            Check("call0 collider0 objId", q0[0].GetProperty("colliders")[0].GetProperty("objId").GetInt32() == 4242);
            Check("call0 collider0 objType", q0[0].GetProperty("colliders")[0].GetProperty("objType").GetString() == "Entity");
            Check("call0 collider1 no data",
                !q0[0].GetProperty("colliders")[1].GetProperty("hasColliderData").GetBoolean());

            JsonElement call1 = mi.GetProperty("calls")[1];
            Check("call1 no overlap detail", call1.GetProperty("overlapQueries")[0].GetProperty("colliders").ValueKind == JsonValueKind.Null);
            Check("call1 before condition name", call1.GetProperty("before").GetProperty("conditionName").GetString() == "ErrorInserterData");

            JsonElement p2 = previews[2];
            Check("p2 unknown condition name", p2.GetProperty("conditionName").GetString() == "Unknown(9999)");
            Check("p2 matchInserter null", p2.GetProperty("matchInserter").ValueKind == JsonValueKind.Null);
            Check("p2 NaN as string", p2.GetProperty("lpos")[0].GetString() == "NaN");
            Check("p2 +Inf as string", p2.GetProperty("lpos")[1].GetString() == "Infinity");
            Check("p2 -Inf as string", p2.GetProperty("lpos")[2].GetString() == "-Infinity");
            Check("p2 content escaped", p2.GetProperty("content").GetString() == NastyContent);
            Check("p2 parameters", p2.GetProperty("parameters").GetArrayLength() == 3);

            JsonElement inTarget = p1.GetProperty("inputTarget");
            Check("p1 inputTarget entity", inTarget.GetProperty("kind").GetString() == "entity");
            Check("p1 inputTarget resolved", inTarget.GetProperty("resolved").GetBoolean());
            Check("p1 inputTarget protoId", inTarget.GetProperty("protoId").GetInt32() == 2001);

            JsonElement outTarget = p1.GetProperty("outputTarget");
            Check("p1 outputTarget prebuild", outTarget.GetProperty("kind").GetString() == "prebuild");
            Check("p1 outputTarget resolved", outTarget.GetProperty("resolved").GetBoolean());
            Check("p1 outputTarget id", outTarget.GetProperty("id").GetInt32() == 5);

            JsonElement unresolved = previews[0].GetProperty("outputTarget");
            Check("p0 outputTarget unresolved", !unresolved.GetProperty("resolved").GetBoolean());

            JsonElement counts = root.GetProperty("conditionCounts");
            Check("conditionCounts Ok", counts.GetProperty("Ok (0)").GetInt32() == 1);
            Check("conditionCounts ErrorInserterData", counts.GetProperty("ErrorInserterData (54)").GetInt32() == 1);

            JsonElement prefabs = root.GetProperty("prefabs");
            Check("prefabs has 2011", prefabs.TryGetProperty("2011", out JsonElement pf));
            Check("prefab isInserter", pf.GetProperty("isInserter").GetBoolean());
            Check("prefab slotPoses", pf.GetProperty("slotPoses").GetArrayLength() == 2);
            CheckVector3("prefab slotPose0 position", pf.GetProperty("slotPoses")[0].GetProperty("position"), TrickyPos);
            Check("prefab portPoses null", pf.GetProperty("portPoses").ValueKind == JsonValueKind.Null);

            if (_failures == 0)
            {
                Console.WriteLine("OK: serializer check passed");
                return 0;
            }

            Console.WriteLine(_failures + " check(s) FAILED");
            return 1;
        }

        // Values chosen so that a naive ToString() would lose bits.
        private static readonly Vector3 TrickyPos = new Vector3(0.1f, -123.456789f, 1.4012985e-45f);
        private static readonly Vector3 TrickyPos2 = new Vector3(3.4028235e+38f, 1.1754944e-38f, -0.0f);
        private static readonly Quaternion TrickyRot = new Quaternion(0.70710678f, -0.00012207031f, 0.33333334f, 0.9999999f);
        private const string NastyContent = "quote\" backslash\\ newline\n tab\t unicodeé ctrl";

        private static string BuildAndSerialize()
        {
            PrefabDesc inserterDesc = New<PrefabDesc>();
            inserterDesc.modelIndex = 77;
            inserterDesc.subId = 3;
            inserterDesc.isInserter = true;
            inserterDesc.inserterSTT = 11;
            inserterDesc.slotPoses = new[]
            {
                new Pose(TrickyPos, TrickyRot),
                new Pose(TrickyPos2, Quaternion.identity)
            };
            inserterDesc.portPoses = null;

            ItemProto inserterProto = New<ItemProto>();
            inserterProto.ID = 2011;
            inserterProto.Name = "Sorter MK.I";

            BuildPreview ok = New<BuildPreview>();
            ok.item = inserterProto;
            ok.desc = inserterDesc;
            ok.condition = EBuildCondition.Ok;
            ok.objId = 0;
            ok.previewIndex = 0;
            ok.outputObjId = 999999;   // deliberately out of range -> resolved:false
            ok.lpos = Vector3.zero;
            ok.lrot = Quaternion.identity;

            BuildPreview bad = New<BuildPreview>();
            bad.item = inserterProto;
            bad.desc = inserterDesc;
            bad.condition = EBuildCondition.ErrorInserterData;
            bad.previewIndex = 1;
            bad.input = ok;
            bad.inputObjId = 12;
            bad.inputFromSlot = 3;
            bad.inputToSlot = -1;
            bad.outputObjId = -5;
            bad.outputFromSlot = -1;
            bad.outputToSlot = 1;
            bad.lpos = TrickyPos;
            bad.lpos2 = TrickyPos2;
            bad.lrot = TrickyRot;
            bad.lrot2 = Quaternion.identity;
            bad.tilt = 0.5f;

            BuildPreview odd = New<BuildPreview>();
            odd.item = null;
            odd.desc = null;
            odd.condition = (EBuildCondition)9999;
            odd.previewIndex = 2;
            odd.lpos = new Vector3(float.NaN, float.PositiveInfinity, float.NegativeInfinity);
            odd.content = NastyContent;
            odd.parameters = new[] { 1, 2, 3, 4, 5 };
            odd.paramCount = 3;

            PlanetFactory factory = New<PlanetFactory>();
            EntityData[] entities = new EntityData[32];
            entities[12].id = 12;
            entities[12].protoId = 2001;
            entities[12].pos = new Vector3(1f, 2f, 3f);
            entities[12].rot = Quaternion.identity;
            factory.entityPool = entities;
            factory.entityCursor = 20;

            PrebuildData[] prebuilds = new PrebuildData[32];
            prebuilds[5].id = 5;
            prebuilds[5].protoId = 2011;
            prebuilds[5].pos = TrickyPos;
            prebuilds[5].rot = TrickyRot;
            factory.prebuildPool = prebuilds;
            factory.prebuildCursor = 10;

            BuildTool_BlueprintPaste tool = New<BuildTool_BlueprintPaste>();
            tool.bpPool = new[] { ok, bad, odd };
            tool.bpCursor = 3;
            tool.blueprintPath = "/tmp/whatever.txt";
            tool.factory = factory;
            tool.yaw = 90f;
            tool.anchorType = 1;
            tool.cursorValid = true;

            MatchRecord rec = new MatchRecord();
            rec.BeginFrame(500, true);

            // Call 0: the input-side match, with collider detail captured.
            MatchCall c0 = new MatchCall();
            c0.Before = PreviewConnState.From(bad);
            c0.OverlapFrom = rec.Overlaps.Count;
            rec.Colliders.Add(new ColliderObservation
            {
                Name = "belt_col",
                GameObjectLayer = 16,
                HasColliderData = true,
                ObjId = 4242,
                ObjType = "Entity",
                Usage = "Build",
                Shape = "Box",
                Link = 7,
                Pos = TrickyPos,
                Ext = new Vector3(0.4f, 0.2f, 0.4f),
                Radius = 0.15f,
                Rot = TrickyRot
            });
            rec.Colliders.Add(new ColliderObservation
            {
                Name = "mystery",
                GameObjectLayer = 18,
                HasColliderData = false
            });
            rec.Overlaps.Add(new OverlapObservation
            {
                Center = TrickyPos,
                Radius = 0.8f,
                LayerMask = 393216,
                ColliderCount = 7,
                ColliderFrom = 0,
                ColliderTake = 2
            });
            c0.After = PreviewConnState.From(bad);
            c0.OverlapTake = rec.Overlaps.Count - c0.OverlapFrom;
            rec.Calls.Add(c0);

            // Call 1: the output-side match, no collider detail.
            MatchCall c1 = new MatchCall();
            c1.Before = PreviewConnState.From(bad);
            c1.OverlapFrom = rec.Overlaps.Count;
            rec.Overlaps.Add(new OverlapObservation
            {
                Center = TrickyPos2,
                Radius = 0.8f,
                LayerMask = 393216,
                ColliderCount = 0,
                ColliderFrom = rec.Colliders.Count,
                ColliderTake = 0
            });
            c1.After = PreviewConnState.From(bad);
            c1.OverlapTake = rec.Overlaps.Count - c1.OverlapFrom;
            rec.Calls.Add(c1);

            DumpContext ctx;
            ctx.OverlapPatchApplied = true;
            ctx.OverlapHookEverFired = true;
            ctx.UnityFrame = 501;
            ctx.Records = new Dictionary<BuildPreview, MatchRecord> { { bad, rec } };

            return Dumper.Serialize(tool, "hotkey", true, true, ctx);
        }

        private static T New<T>()
        {
            return (T)RuntimeHelpers.GetUninitializedObject(typeof(T));
        }

        private static void Check(string what, bool ok)
        {
            if (!ok)
            {
                _failures++;
                Console.WriteLine("FAIL: " + what);
            }
        }

        private static void CheckVector3(string what, JsonElement e, Vector3 expected)
        {
            Check(what + " arity", e.GetArrayLength() == 3);
            CheckFloat(what + ".x", e[0], expected.x);
            CheckFloat(what + ".y", e[1], expected.y);
            CheckFloat(what + ".z", e[2], expected.z);
        }

        private static void CheckQuaternion(string what, JsonElement e, Quaternion expected)
        {
            Check(what + " arity", e.GetArrayLength() == 4);
            CheckFloat(what + ".x", e[0], expected.x);
            CheckFloat(what + ".y", e[1], expected.y);
            CheckFloat(what + ".z", e[2], expected.z);
            CheckFloat(what + ".w", e[3], expected.w);
        }

        private static void CheckFloat(string what, JsonElement e, float expected)
        {
            if (e.ValueKind != JsonValueKind.Number)
            {
                Check(what + " is a number", false);
                return;
            }

            float got = e.GetSingle();
            bool same = BitConverter.SingleToInt32Bits(got) == BitConverter.SingleToInt32Bits(expected);
            if (!same)
            {
                _failures++;
                Console.WriteLine("FAIL: " + what + " round trip: expected " + expected.ToString("G9") +
                    " got " + got.ToString("G9") + " (raw " + e.GetRawText() + ")");
            }
        }

        private static string Excerpt(string s, int at)
        {
            int from = Math.Max(0, at - 200);
            int len = Math.Min(400, s.Length - from);
            return s.Substring(from, len);
        }
    }
}
