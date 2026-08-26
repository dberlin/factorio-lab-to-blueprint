using System;
using System.Collections.Generic;
using System.IO;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace SnapOracle
{
    /// <summary>
    /// stdin -> stdout bridge.  Reads a <see cref="Request"/>, answers a list of
    /// <see cref="Verdict"/>.  <c>--selftest</c> instead runs <see cref="Quat.SelfTest"/>
    /// and exits non-zero if the two substituted Quaternion members disagree with the
    /// shipped game code they were checked against.
    /// </summary>
    internal static class Program
    {
        private static readonly JsonSerializerOptions Opts = new JsonSerializerOptions
        {
            PropertyNameCaseInsensitive = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            IncludeFields = false
        };

        internal static int Main(string[] args)
        {
            if (args.Length > 0 && args[0] == "--probe")
            {
                Probe.Run();
                return 0;
            }
            if (args.Length > 0 && args[0] == "--selftest")
            {
                List<string> bad = Quat.SelfTest();
                foreach (string line in bad)
                {
                    Console.Error.WriteLine(line);
                }
                Console.WriteLine(JsonSerializer.Serialize(new { ok = bad.Count == 0, failures = bad }, Opts));
                return bad.Count == 0 ? 0 : 1;
            }

            string text = Console.In.ReadToEnd();
            Request req;
            try
            {
                req = JsonSerializer.Deserialize<Request>(text, Opts);
            }
            catch (JsonException e)
            {
                Console.Error.WriteLine($"bad request: {e.Message}");
                return 2;
            }
            if (req == null)
            {
                Console.Error.WriteLine("bad request: empty");
                return 2;
            }

            var verdicts = new List<Verdict>();
            foreach (Case c in req.Cases)
            {
                Resolve(c, req.SlotTables);
                verdicts.Add(Run(c));
            }
            using (var writer = new StreamWriter(Console.OpenStandardOutput()))
            {
                writer.Write(JsonSerializer.Serialize(verdicts, Opts));
            }
            return 0;
        }

        /// <summary>Point every <c>slotTable</c> reference at the shared list it names.</summary>
        private static void Resolve(Case c, Dictionary<string, List<SlotPoseDto>> tables)
        {
            foreach (Candidate cand in c.Candidates)
            {
                if (string.IsNullOrEmpty(cand.SlotTable))
                {
                    continue;
                }
                if (!tables.TryGetValue(cand.SlotTable, out List<SlotPoseDto> table))
                {
                    throw new KeyNotFoundException($"case '{c.Name}' names slot table '{cand.SlotTable}', which was not supplied");
                }
                cand.SlotPoses = table;
            }
        }

        private static Verdict Run(Case c)
        {
            var verdict = new Verdict { Name = c.Name };
            try
            {
                var oracle = new Oracle(c);
                BuildPreview bp = new BuildPreview();
                bp.lpos = Json.Vec(c.Lpos);
                bp.lrot = c.Lrot != null ? Json.Quat(c.Lrot) : Quat.Euler(0f, c.Yaw ?? 0f, 0f);
                bp.lpos2 = Json.Vec(c.Lpos2);
                bp.lrot2 = c.Lrot2 != null ? Json.Quat(c.Lrot2) : Quat.Euler(0f, c.Yaw2 ?? 0f, 0f);
                bp.inputObjId = c.InputObjId;
                bp.outputObjId = c.OutputObjId;
                bp.input = c.InputPreview >= 0 ? oracle.Preview(c.Candidates[c.InputPreview]) : null;
                bp.output = c.OutputPreview >= 0 ? oracle.Preview(c.Candidates[c.OutputPreview]) : null;
                bp.desc = new PrefabDesc();

                oracle.MatchInserter(bp, verdict);

                verdict.Condition = bp.condition.ToString();
                verdict.Lpos = Json.Out(bp.lpos);
                verdict.Lrot = Json.Out(bp.lrot);
                verdict.Lpos2 = Json.Out(bp.lpos2);
                verdict.Lrot2 = Json.Out(bp.lrot2);
                verdict.InputObjId = bp.inputObjId;
                verdict.OutputObjId = bp.outputObjId;
                verdict.InputPreview = oracle.IndexOfPreview(bp.input);
                verdict.OutputPreview = oracle.IndexOfPreview(bp.output);
                verdict.InputFromSlot = bp.inputFromSlot;
                verdict.InputToSlot = bp.inputToSlot;
                verdict.InputOffset = bp.inputOffset;
                verdict.OutputFromSlot = bp.outputFromSlot;
                verdict.OutputToSlot = bp.outputToSlot;
                verdict.OutputOffset = bp.outputOffset;
            }
            catch (Exception e)
            {
                // Reported, never swallowed: the driver fails the comparison on any
                // case that carries an `error`.
                verdict.Error = $"{e.GetType().Name}: {e.Message}";
            }
            return verdict;
        }
    }
}
