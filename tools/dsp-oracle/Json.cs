using System.Globalization;
using System.Text;
using UnityEngine;

namespace FlabOracle
{
    /// <summary>
    /// Minimal hand-rolled JSON writer. No dependency on Newtonsoft (which the
    /// game may or may not ship), and full control over float formatting: every
    /// float goes out as "G9", which is the shortest round-tripping form for
    /// System.Single. Nothing here is rounded.
    /// </summary>
    internal sealed class JsonWriter
    {
        private readonly StringBuilder _sb = new StringBuilder(1 << 16);
        private bool _needComma;
        private int _indent;

        public override string ToString()
        {
            return _sb.ToString();
        }

        private void Sep()
        {
            if (_needComma)
            {
                _sb.Append(',');
            }

            _sb.Append('\n');
            _sb.Append(' ', _indent * 2);
            _needComma = true;
        }

        public void BeginObject()
        {
            Sep();
            _sb.Append('{');
            _needComma = false;
            _indent++;
        }

        public void BeginObject(string key)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append('{');
            _needComma = false;
            _indent++;
        }

        public void EndObject()
        {
            _indent--;
            _sb.Append('\n');
            _sb.Append(' ', _indent * 2);
            _sb.Append('}');
            _needComma = true;
        }

        public void BeginArray(string key)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append('[');
            _needComma = false;
            _indent++;
        }

        public void EndArray()
        {
            _indent--;
            _sb.Append('\n');
            _sb.Append(' ', _indent * 2);
            _sb.Append(']');
            _needComma = true;
        }

        private void WriteKeyRaw(string key)
        {
            AppendString(key);
            _sb.Append(": ");
        }

        public void Prop(string key, string value)
        {
            Sep();
            WriteKeyRaw(key);
            if (value == null)
            {
                _sb.Append("null");
            }
            else
            {
                AppendString(value);
            }
        }

        public void Prop(string key, bool value)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append(value ? "true" : "false");
        }

        public void Prop(string key, int value)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append(value.ToString(CultureInfo.InvariantCulture));
        }

        public void Prop(string key, long value)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append(value.ToString(CultureInfo.InvariantCulture));
        }

        public void PropNullableInt(string key, int? value)
        {
            if (value.HasValue)
            {
                Prop(key, value.Value);
            }
            else
            {
                Prop(key, (string)null);
            }
        }

        public void Prop(string key, float value)
        {
            Sep();
            WriteKeyRaw(key);
            AppendFloat(value);
        }

        /// <summary>Doubles go out as "R", the shortest round-tripping form for
        /// System.Double, for the same reason floats go out as "G9".</summary>
        public void Prop(string key, double value)
        {
            Sep();
            WriteKeyRaw(key);
            AppendDouble(value);
        }

        /// <summary>Vector3 as [x, y, z] at full float precision.</summary>
        public void Prop(string key, Vector3 v)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append('[');
            AppendFloat(v.x);
            _sb.Append(", ");
            AppendFloat(v.y);
            _sb.Append(", ");
            AppendFloat(v.z);
            _sb.Append(']');
        }

        /// <summary>Quaternion as [x, y, z, w] at full float precision.</summary>
        public void Prop(string key, Quaternion q)
        {
            Sep();
            WriteKeyRaw(key);
            _sb.Append('[');
            AppendFloat(q.x);
            _sb.Append(", ");
            AppendFloat(q.y);
            _sb.Append(", ");
            AppendFloat(q.z);
            _sb.Append(", ");
            AppendFloat(q.w);
            _sb.Append(']');
        }

        public void PropIntArray(string key, int[] values, int count)
        {
            Sep();
            WriteKeyRaw(key);
            if (values == null)
            {
                _sb.Append("null");
                return;
            }

            if (count > values.Length)
            {
                count = values.Length;
            }

            _sb.Append('[');
            for (int i = 0; i < count; i++)
            {
                if (i > 0)
                {
                    _sb.Append(", ");
                }

                _sb.Append(values[i].ToString(CultureInfo.InvariantCulture));
            }

            _sb.Append(']');
        }

        /// <summary>Whole array; null writes null. The counted overload stays for
        /// callers that hold a pool plus a cursor.</summary>
        public void PropIntArray(string key, int[] values)
        {
            PropIntArray(key, values, values == null ? 0 : values.Length);
        }

        public void PropDoubleArray(string key, double[] values)
        {
            Sep();
            WriteKeyRaw(key);
            if (values == null)
            {
                _sb.Append("null");
                return;
            }

            _sb.Append('[');
            for (int i = 0; i < values.Length; i++)
            {
                if (i > 0)
                {
                    _sb.Append(", ");
                }

                AppendDouble(values[i]);
            }

            _sb.Append(']');
        }

        private void AppendDouble(double value)
        {
            if (double.IsNaN(value))
            {
                _sb.Append("\"NaN\"");
                return;
            }

            if (double.IsPositiveInfinity(value))
            {
                _sb.Append("\"Infinity\"");
                return;
            }

            if (double.IsNegativeInfinity(value))
            {
                _sb.Append("\"-Infinity\"");
                return;
            }

            _sb.Append(value.ToString("R", CultureInfo.InvariantCulture));
        }

        private void AppendFloat(float value)
        {
            if (float.IsNaN(value))
            {
                _sb.Append("\"NaN\"");
                return;
            }

            if (float.IsPositiveInfinity(value))
            {
                _sb.Append("\"Infinity\"");
                return;
            }

            if (float.IsNegativeInfinity(value))
            {
                _sb.Append("\"-Infinity\"");
                return;
            }

            _sb.Append(value.ToString("G9", CultureInfo.InvariantCulture));
        }

        private void AppendString(string s)
        {
            _sb.Append('"');
            for (int i = 0; i < s.Length; i++)
            {
                char c = s[i];
                switch (c)
                {
                    case '"':
                        _sb.Append("\\\"");
                        break;
                    case '\\':
                        _sb.Append("\\\\");
                        break;
                    case '\b':
                        _sb.Append("\\b");
                        break;
                    case '\f':
                        _sb.Append("\\f");
                        break;
                    case '\n':
                        _sb.Append("\\n");
                        break;
                    case '\r':
                        _sb.Append("\\r");
                        break;
                    case '\t':
                        _sb.Append("\\t");
                        break;
                    default:
                        if (c < ' ' || c > '~')
                        {
                            _sb.Append("\\u");
                            _sb.Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                        }
                        else
                        {
                            _sb.Append(c);
                        }

                        break;
                }
            }

            _sb.Append('"');
        }
    }
}
