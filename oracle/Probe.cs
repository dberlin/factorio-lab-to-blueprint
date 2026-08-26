using System;
using System.Linq;
using System.Reflection;
using UnityEngine;

namespace SnapOracle
{
    /// <summary>Throwaway capability probe: which Unity/game maths is callable headless.</summary>
    internal static class Probe
    {
        internal static void Run()
        {
            Try("Vector3 ops", () =>
            {
                Vector3 a = new Vector3(1f, 2f, 3f);
                return $"{a.magnitude} {a.normalized} {Vector3.Dot(a, a)} {Vector3.Angle(Vector3.forward, Vector3.right)}";
            });
            Try("Quaternion identity/ctor/mul", () =>
            {
                Quaternion q = new Quaternion(0f, 0.7071068f, 0f, 0.7071068f);
                Quaternion r = q * Quaternion.identity;
                return $"{r} {(r * Vector3.forward)}";
            });
            Try("Maths.Forward", () => Maths.Forward(new Quaternion(0f, 0.7071068f, 0f, 0.7071068f)).ToString());
            Try("Maths.LookRotation(out)", () =>
            {
                Maths.LookRotation(Vector3.right, Vector3.up, out Quaternion q);
                return q.ToString();
            });
            Try("Quaternion.Euler", () => Quaternion.Euler(0f, 90f, 0f).ToString());
            Try("Quaternion.Slerp", () => Quaternion.Slerp(Quaternion.identity, Quaternion.identity, 0.5f).ToString());
            Try("Pose.GetTransformedBy", () =>
                new Pose(Vector3.right, Quaternion.identity).GetTransformedBy(new Pose(Vector3.up, Quaternion.identity)).ToString());

            Assembly asm = typeof(Maths).Assembly;
            Type kit = asm.GetType("Kit");
            Console.WriteLine($"Kit type: {(kit == null ? "MISSING" : kit.FullName)}");
            if (kit != null)
            {
                foreach (MethodInfo m in kit.GetMethods(BindingFlags.Public | BindingFlags.Static)
                             .Where(m => m.Name.Contains("Closest")))
                {
                    Console.WriteLine($"   {m}");
                }
            }
            foreach (Type t in asm.GetExportedTypes().Where(t => t.Name == "Kit" || t.Name.EndsWith("Kit", StringComparison.Ordinal)))
            {
                Console.WriteLine($"   candidate type {t.FullName}");
            }
        }

        private static void Try(string what, Func<string> f)
        {
            try { Console.WriteLine($"{what,-30} OK   {f()}"); }
            catch (Exception e) { Console.WriteLine($"{what,-30} FAIL {e.GetType().Name}: {e.Message}"); }
        }
    }
}
