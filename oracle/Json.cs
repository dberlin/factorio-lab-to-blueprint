using System;
using UnityEngine;

namespace SnapOracle
{
    /// <summary>Wire arrays to Unity structs and back.</summary>
    internal static class Json
    {
        internal static Vector3 Vec(float[] v)
        {
            if (v == null)
            {
                return Vector3.zero;
            }
            if (v.Length != 3)
            {
                throw new ArgumentException($"a position needs 3 components, got {v.Length}");
            }
            return new Vector3(v[0], v[1], v[2]);
        }

        internal static Quaternion Quat(float[] q)
        {
            if (q == null)
            {
                return UnityEngine.Quaternion.identity;
            }
            if (q.Length != 4)
            {
                throw new ArgumentException($"a rotation needs 4 components (x, y, z, w), got {q.Length}");
            }
            return new Quaternion(q[0], q[1], q[2], q[3]);
        }

        internal static float[] Out(Vector3 v)
        {
            return new float[] { v.x, v.y, v.z };
        }

        internal static float[] Out(Quaternion q)
        {
            return new float[] { q.x, q.y, q.z, q.w };
        }
    }
}
