using System;
using UnityEngine;

namespace SnapOracle
{
    /// <summary>
    /// The two <see cref="Quaternion"/> members the snap ladder uses that CoreCLR
    /// cannot run.
    ///
    /// <para>
    /// Almost all of Unity's <c>Vector3</c> and <c>Quaternion</c> surface is managed
    /// C# inside <c>UnityEngine.CoreModule.dll</c> and runs here untouched -- the
    /// arithmetic operators, <c>magnitude</c>, <c>normalized</c>, <c>Dot</c>,
    /// <c>Angle</c>, <c>identity</c>, <c>Pose.GetTransformedBy</c>, and the game's
    /// own <c>Maths.Forward</c> / <c>Maths.LookRotation</c> / <c>NGPT.Kit</c>.  Only
    /// <c>Quaternion.Euler</c> and <c>Quaternion.Slerp</c> are
    /// <c>[MethodImpl(InternalCall)]</c> thunks into the native player, and both
    /// throw <c>SecurityException: ECall methods must be packaged into a system
    /// module</c> outside the engine.
    /// </para>
    ///
    /// <para>
    /// So they are the ONLY two lines of the transcription that are not shipped game
    /// code, and they are re-implemented here rather than by patching the engine
    /// assembly, which would have put a Cecil rewrite of a native-facing DLL into
    /// the trust chain to save two functions.  <see cref="SelfTest"/> checks both
    /// against shipped game code that DOES run, so the substitution is measured
    /// rather than asserted.
    /// </para>
    /// </summary>
    internal static class Quat
    {
        /// <summary>
        /// <c>Quaternion.Euler</c>, restricted to the pure-yaw form.
        ///
        /// <para>
        /// Every call the ladder makes is <c>Euler(0f, y, 0f)</c> -- four in
        /// <c>belt_slots</c> and four in the body (+90, +180, -90, and the 180 that
        /// flips the output end).  A rotation of <c>y</c> degrees about <c>+Y</c> has
        /// exactly one unit quaternion, <c>(0, sin(y/2), 0, cos(y/2))</c>, whatever
        /// intrinsic order the three-axis form uses, so no convention is being
        /// guessed at.  A non-zero <c>x</c> or <c>z</c> would need Unity's ZXY order
        /// and is refused rather than approximated -- if the ladder ever grows one,
        /// this throws instead of quietly answering.
        /// </para>
        /// </summary>
        internal static Quaternion Euler(float x, float y, float z)
        {
            if (x != 0f || z != 0f)
            {
                throw new NotSupportedException(
                    $"Quat.Euler covers the pure-yaw case the ladder uses; got ({x}, {y}, {z})");
            }
            float half = y * (MathF.PI / 360f);
            return new Quaternion(0f, MathF.Sin(half), 0f, MathF.Cos(half));
        }

        /// <summary>
        /// <c>Quaternion.Slerp</c>: shortest-arc spherical interpolation, <c>t</c>
        /// clamped to <c>[0, 1]</c>, matching Unity's documented behaviour.  Used in
        /// exactly one place -- interpolating a belt's <c>pointRot</c> pair.
        /// </summary>
        internal static Quaternion Slerp(Quaternion a, Quaternion b, float t)
        {
            if (t < 0f) { t = 0f; }
            if (t > 1f) { t = 1f; }
            float dot = (a.x * b.x) + (a.y * b.y) + (a.z * b.z) + (a.w * b.w);
            if (dot < 0f)
            {
                b = new Quaternion(-b.x, -b.y, -b.z, -b.w);
                dot = -dot;
            }
            float wa, wb;
            if (dot > 0.9995f)
            {
                // Nearly parallel: lerp, then renormalise. Slerp's sines both go to
                // zero here and the quotient loses every significant digit.
                wa = 1f - t;
                wb = t;
            }
            else
            {
                float theta = MathF.Acos(dot);
                float sin = MathF.Sin(theta);
                wa = MathF.Sin((1f - t) * theta) / sin;
                wb = MathF.Sin(t * theta) / sin;
            }
            float qx = (wa * a.x) + (wb * b.x);
            float qy = (wa * a.y) + (wb * b.y);
            float qz = (wa * a.z) + (wb * b.z);
            float qw = (wa * a.w) + (wb * b.w);
            float n = MathF.Sqrt((qx * qx) + (qy * qy) + (qz * qz) + (qw * qw));
            return new Quaternion(qx / n, qy / n, qz / n, qw / n);
        }

        /// <summary>
        /// Check the two substitutes against game code that runs for real.  Returns
        /// the failures; an empty list means every check passed.
        ///
        /// <para>
        /// The Euler check is the load-bearing one and it CAN fail: it builds the
        /// same rotation two ways -- once through <see cref="Euler"/>, once through
        /// the game's own managed <c>Maths.LookRotation</c>, which is a verbatim
        /// copy of Unity's algorithm and is not a thunk -- and compares all four
        /// components.  A half-angle written as a full angle, a sign flip, or
        /// degrees left unconverted all move the result far past the tolerance.
        /// </para>
        /// </summary>
        internal static System.Collections.Generic.List<string> SelfTest()
        {
            var bad = new System.Collections.Generic.List<string>();
            const float Tol = 2e-6f;

            // Euler(0, y, 0) must be the rotation that takes +Z to (sin y, 0, cos y)
            // and leaves +Y alone -- which is what LookRotation of that forward with
            // an up of +Y is. The game computes the right-hand side.
            for (int deg = -360; deg <= 360; deg += 5)
            {
                float rad = deg * (MathF.PI / 180f);
                Vector3 fwd = new Vector3(MathF.Sin(rad), 0f, MathF.Cos(rad));
                Maths.LookRotation(fwd, Vector3.up, out Quaternion expected);
                Quaternion got = Euler(0f, deg, 0f);
                // A quaternion and its negation are the same rotation, so compare on
                // whichever sign LookRotation chose.
                if ((expected.w < 0f) != (got.w < 0f))
                {
                    expected = new Quaternion(-expected.x, -expected.y, -expected.z, -expected.w);
                }
                float d = MathF.Abs(expected.x - got.x) + MathF.Abs(expected.y - got.y)
                        + MathF.Abs(expected.z - got.z) + MathF.Abs(expected.w - got.w);
                if (d > Tol)
                {
                    bad.Add($"Euler(0,{deg},0) = {got} but Maths.LookRotation says {expected} (L1 {d})");
                }
                // ... and the game's own Forward() of it must point back down `fwd`.
                Vector3 back = Maths.Forward(got);
                if ((back - fwd).magnitude > 1e-5f)
                {
                    bad.Add($"Maths.Forward(Euler(0,{deg},0)) = {back}, wanted {fwd}");
                }
            }

            // Slerp: the endpoints are exact, the midpoint bisects, and the short arc
            // is the one taken. Vector3.Angle and the operators below are real Unity.
            Quaternion a = Euler(0f, 10f, 0f);
            Quaternion b = Euler(0f, 100f, 0f);
            if ((Maths.Forward(Slerp(a, b, 0f)) - Maths.Forward(a)).magnitude > 1e-6f)
            {
                bad.Add("Slerp(a,b,0) != a");
            }
            if ((Maths.Forward(Slerp(a, b, 1f)) - Maths.Forward(b)).magnitude > 1e-6f)
            {
                bad.Add("Slerp(a,b,1) != b");
            }
            for (int i = 0; i <= 10; i++)
            {
                float t = i / 10f;
                float want = 10f + (90f * t);
                float got = Vector3.Angle(Vector3.forward, Maths.Forward(Slerp(a, b, t)));
                if (MathF.Abs(got - want) > 1e-3f)
                {
                    bad.Add($"Slerp(10deg,100deg,{t}) is {got}deg off +Z, wanted {want}");
                }
            }
            // The short way round: 350 -> 10 must pass through 0, not through 180.
            Quaternion near = Euler(0f, 350f, 0f);
            Quaternion far = Euler(0f, 370f, 0f);
            float mid = Vector3.Angle(Vector3.forward, Maths.Forward(Slerp(near, far, 0.5f)));
            if (mid > 1e-3f)
            {
                bad.Add($"Slerp took the long arc: midpoint of 350->10 is {mid}deg off +Z");
            }
            return bad;
        }
    }
}
