var __defProp = Object.defineProperty;
var __defNormalProp = (obj, key, value) => key in obj ? __defProp(obj, key, { enumerable: !0, configurable: !0, writable: !0, value }) : obj[key] = value;
var __publicField = (obj, key, value) => __defNormalProp(obj, typeof key != "symbol" ? key + "" : key, value);
import { CpSat } from "./cp_sat_api.js";
import {
  CpSolverStatus
} from "./generated/cp_model.js";
const INT64_MIN = { low: 0, high: -2147483648 }, INT64_MAX = { low: -1, high: 2147483647 };
function assert(condition, message) {
  if (!condition)
    throw new Error(message);
}
class ValueError extends Error {
  constructor(message) {
    super(message), this.name = "ValueError";
  }
}
class RuntimeError extends Error {
  constructor(message) {
    super(message), this.name = "RuntimeError";
  }
}
class ArithmeticError extends Error {
  constructor(message) {
    super(message), this.name = "ArithmeticError";
  }
}
class NotImplementedError extends Error {
  constructor(message) {
    super(message), this.name = "NotImplementedError";
  }
}
function valueError(condition, message) {
  if (!condition)
    throw new ValueError(message);
}
function runtimeError(condition, message) {
  if (!condition)
    throw new RuntimeError(message);
}
function asInt64(value) {
  return assert(Number.isInteger(value), `expected integer value, got ${value}`), value;
}
function normalizeInt64(value) {
  return typeof value == "number" ? asInt64(value) : value;
}
function int64ObjectToBigInt(value) {
  return BigInt(value.high) * 0x100000000n + BigInt(value.low >>> 0);
}
function protoInt64ToBigInt(value) {
  return typeof value == "number" || typeof value == "string" ? BigInt(value) : int64ObjectToBigInt(value);
}
function protoInt64ToString(value) {
  return protoInt64ToBigInt(value).toString();
}
function compareProtoInt64(left, right) {
  const leftValue = protoInt64ToBigInt(left), rightValue = protoInt64ToBigInt(right);
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}
function bigintToProtoInt64(value) {
  return value >= BigInt(Number.MIN_SAFE_INTEGER) && value <= BigInt(Number.MAX_SAFE_INTEGER) ? Number(value) : {
    low: Number(BigInt.asIntN(32, value)),
    high: Number(BigInt.asIntN(32, value >> 32n))
  };
}
function isInt64Min(value) {
  return value === "-9223372036854775808" || typeof value == "object" && value.low === 0 && value.high === -2147483648;
}
function isInt64Max(value) {
  return value === "9223372036854775807" || typeof value == "object" && value.low === -1 && value.high === 2147483647;
}
function isProtoInt64Object(value) {
  return typeof value == "object" && value !== null && "low" in value && "high" in value && typeof value.low == "number" && typeof value.high == "number";
}
function isProtoInt64String(value) {
  return typeof value == "string" && /^-?\d+$/.test(value);
}
function isProtoInt64Constant(value) {
  return typeof value == "number" || isProtoInt64String(value) || isProtoInt64Object(value);
}
function adjustedProtoInt64ToBigInt(value, offset) {
  return protoInt64ToBigInt(value) - BigInt(offset);
}
function adjustedProtoInt64ToString(value, offset) {
  return Number.isInteger(offset) ? adjustedProtoInt64ToBigInt(value, offset).toString() : String(protoInt64ToNumber(value) - offset);
}
function compareAdjustedProtoInt64(left, right, offset) {
  if (!Number.isInteger(offset)) {
    const leftValue2 = protoInt64ToNumber(left) - offset, rightValue2 = protoInt64ToNumber(right) - offset;
    return leftValue2 < rightValue2 ? -1 : leftValue2 > rightValue2 ? 1 : 0;
  }
  const leftValue = adjustedProtoInt64ToBigInt(left, offset), rightValue = adjustedProtoInt64ToBigInt(right, offset);
  return leftValue < rightValue ? -1 : leftValue > rightValue ? 1 : 0;
}
function adjustDomainEndpoint(value, offset) {
  return isInt64Min(value) || isInt64Max(value) ? value : typeof value == "number" ? asInt64(value - offset) : bigintToProtoInt64(typeof value == "string" ? BigInt(value) - BigInt(offset) : int64ObjectToBigInt(value) - BigInt(offset));
}
function protoInt64ToNumber(value) {
  return value === void 0 ? 0 : typeof value == "number" ? value : typeof value == "string" ? Number(value) : value.high * 4294967296 + (value.low >>> 0);
}
function cloneProto(value) {
  return JSON.parse(JSON.stringify(value));
}
function rebuildFromLinearExpressionProto(proto, _modelProto) {
  const vars = proto.vars ?? [], coeffs = proto.coeffs ?? [];
  if (valueError(vars.length === coeffs.length, "linear expression proto vars and coeffs must have the same length"), vars.length === 0)
    return protoInt64ToNumber(proto.offset);
  const terms = /* @__PURE__ */ new Map();
  for (let index = 0; index < vars.length; index += 1)
    terms.set(vars[index], Number(protoInt64ToNumber(coeffs[index])));
  return new LinearExpr(null, terms, protoInt64ToNumber(proto.offset));
}
function rebuild_from_linear_expression_proto(proto, modelProto) {
  return rebuildFromLinearExpressionProto(proto, modelProto);
}
function evaluateLinearExpression(response, expression) {
  const expr = LinearExpr.from(expression);
  let value = expr.offset;
  for (const [index, coeff] of expr.terms) {
    const variableValue = response.solution?.[index];
    assert(typeof variableValue == "number", `missing numeric solution value for variable ${index}`), value += coeff * variableValue;
  }
  return value;
}
function evaluateBooleanLiteral(response, literal) {
  if (typeof literal == "number")
    return literal !== 0;
  if (literal === !0 || literal === !1)
    return literal;
  const index = literal instanceof NotBoolVar ? literal.variable.index : literal.index, value = response.solution?.[index];
  assert(typeof value == "number", `missing numeric solution value for literal ${index}`);
  const truth = value !== 0;
  return literal instanceof NotBoolVar ? !truth : truth;
}
function literalIndex(literal) {
  if (typeof literal == "number") {
    if (literal === 0) return !1;
    if (literal === 1) return !0;
    throw new TypeError("literal numeric constants must be 0 or 1");
  }
  if (literal === !0) return !0;
  if (literal === !1) return !1;
  if (!(literal instanceof BoolVar || literal instanceof NotBoolVar))
    throw new TypeError("literal must be a Boolean variable or its negation");
  return literal.index;
}
function objectIsATrueLiteral(literal) {
  if (literal instanceof IntVar) {
    const domain = literal.model.proto().variables?.[literal.index]?.domain ?? [];
    return domain.length === 2 && protoInt64ToNumber(domain[0]) === 1 && protoInt64ToNumber(domain[1]) === 1;
  }
  if (literal instanceof NotBoolVar) {
    const domain = literal.variable.model.proto().variables?.[literal.variable.index]?.domain ?? [];
    return domain.length === 2 && protoInt64ToNumber(domain[0]) === 0 && protoInt64ToNumber(domain[1]) === 0;
  }
  return typeof literal == "boolean" ? literal : typeof literal == "number" && Number.isInteger(literal) ? literal === 1 || literal === -1 : !1;
}
function object_is_a_true_literal(literal) {
  return objectIsATrueLiteral(literal);
}
function objectIsAFalseLiteral(literal) {
  if (literal instanceof IntVar) {
    const domain = literal.model.proto().variables?.[literal.index]?.domain ?? [];
    return domain.length === 2 && protoInt64ToNumber(domain[0]) === 0 && protoInt64ToNumber(domain[1]) === 0;
  }
  if (literal instanceof NotBoolVar) {
    const domain = literal.variable.model.proto().variables?.[literal.variable.index]?.domain ?? [];
    return domain.length === 2 && protoInt64ToNumber(domain[0]) === 1 && protoInt64ToNumber(domain[1]) === 1;
  }
  return typeof literal == "boolean" ? !literal : typeof literal == "number" && Number.isInteger(literal) ? literal === 0 || literal === -2 : !1;
}
function object_is_a_false_literal(literal) {
  return objectIsAFalseLiteral(literal);
}
function requireSameModel(model, owner, what) {
  if (model !== owner)
    throw new Error(`${what} belongs to a different CpModel`);
}
function mergeTerms(terms, index, coeff) {
  const next = (terms.get(index) ?? 0) + coeff;
  next === 0 ? terms.delete(index) : terms.set(index, next);
}
function variableDisplayName(model, index) {
  return model?.proto().variables?.[index]?.name || `var${index}`;
}
function renderLinearExprDisplay(node, model) {
  switch (node.kind) {
    case "const":
      return String(node.value);
    case "var":
      return variableDisplayName(model, node.index);
    case "not":
      return `not(${variableDisplayName(model, node.index)})`;
    case "mul": {
      const value = renderLinearExprDisplay(node.value, model);
      return node.coeff === 1 ? value : node.coeff === -1 ? `(-${value})` : `(${node.coeff} * ${value})`;
    }
    case "sum":
      return formatDisplaySum(node.values, model);
    case "weighted":
      return formatWeightedDisplaySum(node.values, node.coeffs, model);
  }
}
function renderLinearExprDisplayRepr(node, model) {
  switch (node.kind) {
    case "const":
      return Number.isInteger(node.value) ? `IntConstant(${node.value})` : `FloatConstant(${node.value})`;
    case "var":
      return model?.getIntVarFromProtoIndex(node.index)?.repr() ?? `var${node.index}`;
    case "not":
      return `NotBooleanVariable(var_index=${node.index})`;
    case "mul": {
      const valueRepr = renderLinearExprDisplayRepr(node.value, model);
      return `${Number.isInteger(node.coeff) ? "IntAffine" : "FloatAffine"}(expr=${valueRepr}, coeff=${node.coeff}, offset=0)`;
    }
    case "sum": {
      const values = [];
      let integerOffset = 0, floatOffset = 0, hasFloatOffset = !1;
      for (const value of node.values)
        value.kind === "const" ? Number.isInteger(value.value) && !hasFloatOffset ? integerOffset += value.value : (hasFloatOffset = !0, floatOffset += value.value) : values.push(renderLinearExprDisplayRepr(value, model));
      return hasFloatOffset ? `SumArray(${values.join(", ")}, float_offset=${floatOffset + integerOffset})` : integerOffset !== 0 ? `SumArray(${values.join(", ")}, int_offset=${integerOffset})` : `SumArray(${values.join(", ")})`;
    }
    case "weighted":
      return `WeightedSum(${node.values.map((value) => renderLinearExprDisplayRepr(value, model)).join(", ")}, coeffs=[${node.coeffs.join(", ")}])`;
  }
}
function formatDisplaySum(values, model) {
  const nonConstantValues = [];
  let constant = 0;
  for (const value of values)
    value.kind === "const" ? constant += value.value : nonConstantValues.push(value);
  if ((constant !== 0 || nonConstantValues.length === 0) && nonConstantValues.push({ kind: "const", value: constant }), nonConstantValues.length === 0)
    return "0";
  const [first, ...rest] = nonConstantValues;
  let text = renderLinearExprDisplay(first, model);
  for (const value of rest)
    value.kind === "const" && value.value < 0 ? text += ` - ${Math.abs(value.value)}` : text += ` + ${renderLinearExprDisplay(value, model)}`;
  return nonConstantValues.length > 1 ? `(${text})` : text;
}
function formatWeightedDisplaySum(values, coeffs, model) {
  const pieces = [];
  for (let index = 0; index < values.length; index += 1) {
    const coeff = coeffs[index];
    if (coeff === 0)
      continue;
    const value = values[index];
    if (value.kind === "const") {
      const scaled = value.value * coeff;
      scaled !== 0 && pieces.push({ sign: scaled < 0 ? -1 : 1, text: String(Math.abs(scaled)) });
      continue;
    }
    const sign = coeff < 0 ? -1 : 1, absCoeff = Math.abs(coeff), valueText = renderLinearExprDisplay(value, model);
    pieces.push({ sign, text: absCoeff === 1 ? valueText : `${absCoeff} * ${valueText}` });
  }
  if (pieces.length === 0)
    return "0";
  const [first, ...rest] = pieces;
  let text = first.sign < 0 ? `-${first.text}` : first.text;
  for (const piece of rest)
    text += piece.sign < 0 ? ` - ${piece.text}` : ` + ${piece.text}`;
  return pieces.length > 1 || pieces[0].sign < 0 ? `(${text})` : text;
}
function appendDisplaySumValues(values, node) {
  node.kind === "sum" ? values.push(...node.values) : values.push(node);
}
function unsupportedNativeOperatorCoercion() {
  throw new NotImplementedError("native JavaScript operators are not supported for CP-SAT expressions; use the explicit high-level API methods");
}
function expressionList(first, rest) {
  return rest.length > 0 ? [first, ...rest] : typeof first == "number" || first instanceof IntVar || first instanceof NotBoolVar || first instanceof LinearExpr ? [first] : Array.from(first);
}
function iterableValues(first, rest) {
  return rest.length > 0 ? [first, ...rest] : typeof first == "number" || first instanceof IntVar || first instanceof NotBoolVar || first instanceof LinearExpr ? [first] : Array.from(first);
}
function literalList(first, rest) {
  return rest.length > 0 ? [first, ...rest] : typeof first == "number" || typeof first == "boolean" || first instanceof BoolVar || first instanceof NotBoolVar ? [first] : Array.from(first);
}
class LinearExpr {
  constructor(model, terms = /* @__PURE__ */ new Map(), offset = 0, display = null) {
    __publicField(this, "model");
    __publicField(this, "terms");
    __publicField(this, "offset");
    __publicField(this, "display");
    this.model = model, this.terms = new Map(terms), this.offset = offset, this.display = display;
  }
  static constant(value) {
    return new LinearExpr(null, /* @__PURE__ */ new Map(), value, { kind: "const", value });
  }
  static sum(values, ...rest) {
    return sum(values, ...rest);
  }
  static Sum(values, ...rest) {
    return LinearExpr.sum(values, ...rest);
  }
  static weightedSum(values, coeffs) {
    return weightedSum(values, coeffs);
  }
  static weighted_sum(values, coeffs) {
    return LinearExpr.weightedSum(values, coeffs);
  }
  static WeightedSum(values, coeffs) {
    return LinearExpr.weightedSum(values, coeffs);
  }
  static term(variable, coeff) {
    return term(variable, coeff);
  }
  static Term(variable, coeff) {
    return LinearExpr.term(variable, coeff);
  }
  static affine(expression, coeff, offset) {
    return LinearExpr.from(expression).times(coeff).plus(offset);
  }
  static from(value) {
    if (typeof value == "number")
      return LinearExpr.constant(value);
    if (value instanceof LinearExpr)
      return value;
    if (value instanceof NotBoolVar)
      return value.expr();
    if (!(value instanceof IntVar))
      throw new TypeError("expected integer variable or linear expression");
    return value.expr();
  }
  plus(value, coeff = 1) {
    const other = coeff === 1 ? LinearExpr.from(value) : LinearExpr.from(value).times(coeff), model = this.model ?? other.model;
    this.model && other.model && requireSameModel(this.model, other.model, "linear expression");
    const terms = new Map(this.terms);
    for (const [index, termCoeff] of other.terms)
      mergeTerms(terms, index, termCoeff);
    const displayValues = [];
    return appendDisplaySumValues(displayValues, this.displayNodeForRendering()), appendDisplaySumValues(displayValues, other.displayNodeForRendering()), new LinearExpr(model, terms, this.offset + other.offset, { kind: "sum", values: displayValues });
  }
  minus(value) {
    return this.plus(value, -1);
  }
  times(coeff) {
    if (typeof coeff != "number" || !Number.isFinite(coeff))
      throw new TypeError(`expected finite numeric coefficient, got ${coeff}`);
    const terms = /* @__PURE__ */ new Map();
    for (const [index, termCoeff] of this.terms)
      mergeTerms(terms, index, termCoeff * coeff);
    let displayCoeff = coeff, displayValue = this.displayNodeForRendering();
    return displayValue.kind === "mul" && (displayCoeff *= displayValue.coeff, displayValue = displayValue.value), new LinearExpr(this.model, terms, this.offset * coeff, {
      kind: "mul",
      coeff: displayCoeff,
      value: displayValue
    });
  }
  neg() {
    return this.times(-1);
  }
  abs() {
    throw new NotImplementedError(
      "calling abs() on a linear expression is not supported, please use CpModel.add_abs_equality"
    );
  }
  __abs__() {
    return this.abs();
  }
  div(_value) {
    throw new NotImplementedError(
      "calling // on a linear expression is not supported, please use CpModel.add_division_equality"
    );
  }
  __div__(value) {
    return this.div(value);
  }
  truediv(_value) {
    return this.div(_value);
  }
  __truediv__(value) {
    return this.truediv(value);
  }
  mod(_value) {
    throw new NotImplementedError(
      "calling %% on a linear expression is not supported, please use CpModel.add_modulo_equality"
    );
  }
  __mod__(value) {
    return this.mod(value);
  }
  __pow__(_value) {
    throw new NotImplementedError("calling ** on a linear expression is not supported");
  }
  __lshift__(_value) {
    throw new NotImplementedError("calling << on a linear expression is not supported");
  }
  __rshift__(_value) {
    throw new NotImplementedError("calling >> on a linear expression is not supported");
  }
  __and__(_value) {
    throw new NotImplementedError("calling & on a linear expression is not supported");
  }
  __or__(_value) {
    throw new NotImplementedError("calling | on a linear expression is not supported");
  }
  __xor__(_value) {
    throw new NotImplementedError("calling ^ on a linear expression is not supported");
  }
  eq(value) {
    return new BoundedLinearExpr(this.minus(value), 0, 0);
  }
  ne(value) {
    return isProtoInt64Constant(value) && isInt64Min(value) ? new BoundedLinearExpr(this, bigintToProtoInt64(-9223372036854775807n), INT64_MAX) : isProtoInt64Constant(value) && isInt64Max(value) ? new BoundedLinearExpr(this, INT64_MIN, bigintToProtoInt64(9223372036854775806n)) : new BoundedLinearExpr(this.minus(value), INT64_MIN, -1, [INT64_MIN, -1, 1, INT64_MAX]);
  }
  le(value) {
    return isProtoInt64Constant(value) ? new BoundedLinearExpr(this, INT64_MIN, value) : new BoundedLinearExpr(this.minus(value), INT64_MIN, 0);
  }
  lt(value) {
    if (isProtoInt64Constant(value) && isInt64Min(value))
      throw new ArithmeticError("integer expressions cannot be less than INT_MIN");
    return new BoundedLinearExpr(this.minus(value), INT64_MIN, -1);
  }
  ge(value) {
    return isProtoInt64Constant(value) ? new BoundedLinearExpr(this, value, INT64_MAX) : new BoundedLinearExpr(this.minus(value), 0, INT64_MAX);
  }
  gt(value) {
    if (isProtoInt64Constant(value) && isInt64Max(value))
      throw new ArithmeticError("integer expressions cannot be greater than INT_MAX");
    return new BoundedLinearExpr(this.minus(value), 1, INT64_MAX);
  }
  toProto() {
    const vars = [], coeffs = [];
    for (const [index, coeff] of this.terms)
      vars.push(index), coeffs.push(asInt64(coeff));
    const proto = { vars, coeffs };
    return this.offset !== 0 && (proto.offset = asInt64(this.offset)), proto;
  }
  toString() {
    if (this.display)
      return renderLinearExprDisplay(this.display, this.model);
    if (this.terms.size === 1 && this.offset !== 0) {
      const [[index, coeff]] = Array.from(this.terms), variable = this.model?.getIntVarFromProtoIndex(index);
      if (variable instanceof BoolVar && coeff === -this.offset)
        return `(${this.offset} * not(${variable}))`;
    }
    const pieces = [];
    let singleTermNeedsParens = !1;
    for (const [index, coeff] of this.terms) {
      const name = this.model?.proto().variables?.[index]?.name || `var${index}`;
      coeff === 1 ? pieces.push(name) : coeff === -1 ? (pieces.push(`-${name}`), singleTermNeedsParens = !0) : (pieces.push(`${coeff} * ${name}`), singleTermNeedsParens = !0);
    }
    (this.offset !== 0 || pieces.length === 0) && (pieces.push(String(this.offset)), singleTermNeedsParens = !1);
    const [first, ...rest] = pieces, value = rest.reduce((text, piece) => piece.startsWith("-") ? `${text} - ${piece.slice(1)}` : `${text} + ${piece}`, first);
    return pieces.length > 1 || singleTermNeedsParens ? `(${value})` : value;
  }
  [Symbol.toPrimitive](hint) {
    return hint === "string" ? this.toString() : unsupportedNativeOperatorCoercion();
  }
  displayNodeForRendering() {
    if (this.display)
      return this.display;
    if (this.terms.size === 0)
      return { kind: "const", value: this.offset };
    const values = Array.from(this.terms, ([index, coeff]) => {
      const variable = { kind: "var", index };
      return coeff === 1 ? variable : { kind: "mul", coeff, value: variable };
    });
    return this.offset !== 0 && values.push({ kind: "const", value: this.offset }), values.length === 1 ? values[0] : { kind: "sum", values };
  }
  hasFloatingPointTerms() {
    return this.offset !== 0 && !Number.isInteger(this.offset) || Array.from(this.terms.values()).some((coeff) => !Number.isInteger(coeff));
  }
  isInteger() {
    return !this.hasFloatingPointTerms();
  }
  is_integer() {
    return this.isInteger();
  }
  repr() {
    if (this.terms.size === 0)
      return Number.isInteger(this.offset) ? `IntConstant(${this.offset})` : `FloatConstant(${this.offset})`;
    if (this.terms.size === 1) {
      const [[index, coeff]] = Array.from(this.terms);
      if (coeff === 1 && this.offset === 0)
        return this.model?.getIntVarFromProtoIndex(index)?.repr() ?? String(this);
      const variableRepr = this.model?.getIntVarFromProtoIndex(index)?.repr() ?? `var${index}`;
      return Number.isInteger(coeff) && Number.isInteger(this.offset) ? `IntAffine(expr=${variableRepr}, coeff=${coeff}, offset=${this.offset})` : `FloatAffine(expr=${variableRepr}, coeff=${coeff}, offset=${this.offset})`;
    }
    if (this.display?.kind === "sum")
      return renderLinearExprDisplayRepr(this.display, this.model);
    const variables = Array.from(this.terms, ([index]) => this.model?.getIntVarFromProtoIndex(index)?.repr() ?? `var${index}`), coeffs = Array.from(this.terms.values());
    return this.offset === 0 && coeffs.every((coeff) => coeff === 1) ? `SumArray(${variables.join(", ")})` : coeffs.every((coeff) => Number.isInteger(coeff)) && Number.isInteger(this.offset) ? `IntWeightedSum([${variables.join(", ")}], [${coeffs.join(", ")}], ${this.offset})` : `FloatWeightedSum([${variables.join(", ")}], [${coeffs.join(", ")}], ${this.offset})`;
  }
  toFloatObjective(maximize = !1) {
    return {
      vars: Array.from(this.terms.keys()),
      coeffs: Array.from(this.terms.values()),
      offset: this.offset,
      maximize
    };
  }
}
class BoundedLinearExpr {
  constructor(expression, lowerBound, upperBound, domain) {
    __publicField(this, "expression", expression);
    __publicField(this, "lowerBound", lowerBound);
    __publicField(this, "upperBound", upperBound);
    __publicField(this, "domain", domain);
  }
  toString() {
    const normalizedExpression = new LinearExpr(this.expression.model, this.expression.terms, 0), expressionText = String(normalizedExpression), lower = adjustedProtoInt64ToString(this.lowerBound, this.expression.offset), upper = adjustedProtoInt64ToString(this.upperBound, this.expression.offset);
    if (this.domain !== void 0) {
      if (this.domain.length === 4 && isInt64Min(this.domain[0]) && protoInt64ToNumber(this.domain[1]) === -1 && protoInt64ToNumber(this.domain[2]) === 1 && isInt64Max(this.domain[3]))
        return `${expressionText} != ${-this.expression.offset}`;
      const [firstLower, firstUpper, secondLower, secondUpper] = this.domain.map(
        (value) => adjustedProtoInt64ToString(value, this.expression.offset)
      );
      if (isInt64Min(this.domain[0]) && secondLower !== void 0 && isInt64Max(this.domain[3])) {
        const firstUpperEnd = (BigInt(firstUpper) + 1n).toString(), secondLowerStart = (BigInt(secondLower) - 1n).toString();
        return `(${expressionText}) not in [${firstUpperEnd}, ${secondLowerStart}]`;
      }
      return `${expressionText} in [${[firstLower, firstUpper, secondLower, secondUpper].filter((value) => value !== void 0).join(", ")}]`;
    }
    return isInt64Min(this.lowerBound) && isInt64Max(this.upperBound) ? `True (unbounded expr ${expressionText})` : isInt64Min(this.lowerBound) ? `${expressionText} <= ${upper}` : isInt64Max(this.upperBound) ? `${expressionText} >= ${lower}` : compareAdjustedProtoInt64(this.lowerBound, this.upperBound, this.expression.offset) === 0 ? `${expressionText} == ${lower}` : `${lower} <= ${expressionText} <= ${upper}`;
  }
  [Symbol.toPrimitive](hint) {
    return hint === "string" ? this.toString() : unsupportedNativeOperatorCoercion();
  }
}
class BoundedLinearExpression extends BoundedLinearExpr {
  constructor(expression, domain) {
    const linear = LinearExpr.from(expression);
    valueError(domain instanceof Domain, "domain must be a Domain");
    const flatDomain = domain.flatIntervals;
    valueError(flatDomain.length >= 2 && flatDomain.length % 2 === 0, "domain must contain complete intervals"), flatDomain.length === 2 ? super(linear, flatDomain[0], flatDomain[1]) : super(linear, flatDomain[0], flatDomain[flatDomain.length - 1], flatDomain);
  }
}
class IntVar {
  constructor(model, index, _name = "") {
    __publicField(this, "model", model);
    __publicField(this, "index", index);
  }
  get name() {
    return this.model.proto().variables?.[this.index]?.name ?? "";
  }
  get model_proto() {
    return this.model.proto();
  }
  expr() {
    return new LinearExpr(this.model, /* @__PURE__ */ new Map([[this.index, 1]]), 0, { kind: "var", index: this.index });
  }
  plus(value, coeff = 1) {
    return this.expr().plus(value, coeff);
  }
  __add__(value) {
    return this.plus(value);
  }
  minus(value) {
    return this.expr().minus(value);
  }
  times(coeff) {
    return this.expr().times(coeff);
  }
  __mul__(coeff) {
    return this.times(coeff);
  }
  neg() {
    return this.expr().neg();
  }
  abs() {
    return this.expr().abs();
  }
  __abs__() {
    return this.abs();
  }
  div(value) {
    return this.expr().div(value);
  }
  __div__(value) {
    return this.div(value);
  }
  truediv(value) {
    return this.expr().truediv(value);
  }
  __truediv__(value) {
    return this.truediv(value);
  }
  mod(value) {
    return this.expr().mod(value);
  }
  __mod__(value) {
    return this.mod(value);
  }
  __pow__(value) {
    return this.expr().__pow__(value);
  }
  __lshift__(value) {
    return this.expr().__lshift__(value);
  }
  __rshift__(value) {
    return this.expr().__rshift__(value);
  }
  __and__(value) {
    return this.expr().__and__(value);
  }
  __or__(value) {
    return this.expr().__or__(value);
  }
  __xor__(value) {
    return this.expr().__xor__(value);
  }
  isInteger() {
    return !0;
  }
  is_integer() {
    return !0;
  }
  isBoolean() {
    return this.model.isBooleanIndex(this.index);
  }
  get is_boolean() {
    return this.isBoolean();
  }
  negated() {
    if (!this.isBoolean())
      throw new TypeError("negated() is only supported for Boolean variables.");
    return new NotBoolVar(this);
  }
  toString() {
    const variable = this.model.proto().variables?.[this.index];
    if (variable?.name)
      return variable.name;
    const domain = variable?.domain ?? [];
    return domain.length >= 2 && protoInt64ToString(domain[0]) === protoInt64ToString(domain[1]) ? protoInt64ToString(domain[0]) : this.isBoolean() ? `b${this.index}` : `x${this.index}`;
  }
  [Symbol.toPrimitive](hint) {
    return hint === "string" ? this.toString() : unsupportedNativeOperatorCoercion();
  }
  debugString() {
    const name = String(this), domain = this.model.proto().variables?.[this.index]?.domain ?? [];
    return `${name}(${formatDomain(domain)})`;
  }
  repr() {
    return this.debugString();
  }
  eq(value) {
    return this.expr().eq(value);
  }
  ne(value) {
    return this.expr().ne(value);
  }
  le(value) {
    return this.expr().le(value);
  }
  lt(value) {
    return this.expr().lt(value);
  }
  __lt__(value) {
    return this.lt(value);
  }
  ge(value) {
    return this.expr().ge(value);
  }
  gt(value) {
    return this.expr().gt(value);
  }
  __gt__(value) {
    return this.gt(value);
  }
}
class BoolVar extends IntVar {
  get literalIndex() {
    return this.index;
  }
  not() {
    return this.negated();
  }
}
function isBoolExpression(value) {
  return value instanceof BoolVar || value instanceof NotBoolVar;
}
class NotBoolVar {
  constructor(variable) {
    __publicField(this, "variable", variable);
    __publicField(this, "model");
    __publicField(this, "index");
    __publicField(this, "name");
    this.model = variable.model, this.index = -variable.index - 1, this.name = variable.name ? `not(${variable.name})` : "";
  }
  get model_proto() {
    return this.model.proto();
  }
  not() {
    return this.variable;
  }
  negated() {
    return this.variable;
  }
  plus(value, coeff = 1) {
    return this.expr().plus(value, coeff);
  }
  __add__(value) {
    return this.plus(value);
  }
  minus(value) {
    return this.expr().minus(value);
  }
  times(coeff) {
    return this.expr().times(coeff);
  }
  __mul__(coeff) {
    return this.times(coeff);
  }
  neg() {
    return this.expr().neg();
  }
  abs() {
    return this.expr().abs();
  }
  __abs__() {
    return this.abs();
  }
  div(value) {
    return this.expr().div(value);
  }
  __div__(value) {
    return this.div(value);
  }
  truediv(value) {
    return this.expr().truediv(value);
  }
  __truediv__(value) {
    return this.truediv(value);
  }
  mod(value) {
    return this.expr().mod(value);
  }
  __mod__(value) {
    return this.mod(value);
  }
  __pow__(value) {
    return this.expr().__pow__(value);
  }
  __lshift__(value) {
    return this.expr().__lshift__(value);
  }
  __rshift__(value) {
    return this.expr().__rshift__(value);
  }
  __and__(value) {
    return this.expr().__and__(value);
  }
  __or__(value) {
    return this.expr().__or__(value);
  }
  __xor__(value) {
    return this.expr().__xor__(value);
  }
  isInteger() {
    return !0;
  }
  is_integer() {
    return !0;
  }
  expr() {
    return new LinearExpr(this.model, /* @__PURE__ */ new Map([[this.variable.index, -1]]), 1, {
      kind: "not",
      index: this.variable.index
    });
  }
  toString() {
    return `not(${this.variable})`;
  }
  [Symbol.toPrimitive](hint) {
    return hint === "string" ? this.toString() : unsupportedNativeOperatorCoercion();
  }
  repr() {
    return `NotBooleanVariable(var_index=${this.variable.index})`;
  }
}
class FlatIntExpr {
  constructor(expression) {
    __publicField(this, "vars");
    __publicField(this, "coeffs");
    __publicField(this, "offset");
    if (expression instanceof FlatIntExpr || expression instanceof FlatFloatExpr) {
      valueError(expression.coeffs.every((coeff) => Number.isInteger(coeff)) && Number.isInteger(expression.offset), "expression is not integer"), this.vars = [...expression.vars], this.coeffs = [...expression.coeffs], this.offset = expression.offset;
      return;
    }
    const linear = LinearExpr.from(expression);
    valueError(linear.isInteger(), "expression is not integer");
    const vars = [], coeffs = [];
    for (const [index, coeff] of linear.terms)
      assert(linear.model, `missing model for variable ${index}`), vars.push(linear.model.getIntVarFromProtoIndex(index)), coeffs.push(coeff);
    this.vars = vars, this.coeffs = coeffs, this.offset = linear.offset;
  }
  expr() {
    const model = this.vars[0]?.model ?? null, terms = /* @__PURE__ */ new Map();
    for (let index = 0; index < this.vars.length; index += 1)
      terms.set(this.vars[index].index, this.coeffs[index]);
    return new LinearExpr(model, terms, this.offset);
  }
  plus(value) {
    return this.expr().plus(value);
  }
  minus(value) {
    return this.expr().minus(value);
  }
  times(coeff) {
    return this.expr().times(coeff);
  }
  toString() {
    return formatFlatExpression(this.vars, this.coeffs, this.offset);
  }
  repr() {
    return `FlatIntExpr([${this.vars.map((variable) => variable.repr()).join(", ")}], [${this.coeffs.join(", ")}], ${this.offset})`;
  }
}
class FlatFloatExpr {
  constructor(expression) {
    __publicField(this, "vars");
    __publicField(this, "coeffs");
    __publicField(this, "offset");
    if (expression instanceof FlatIntExpr || expression instanceof FlatFloatExpr) {
      this.vars = [...expression.vars], this.coeffs = expression.coeffs.map((coeff) => Number(coeff)), this.offset = Number(expression.offset);
      return;
    }
    const linear = LinearExpr.from(expression), vars = [], coeffs = [];
    for (const [index, coeff] of linear.terms)
      assert(linear.model, `missing model for variable ${index}`), vars.push(linear.model.getIntVarFromProtoIndex(index)), coeffs.push(Number(coeff));
    this.vars = vars, this.coeffs = coeffs, this.offset = Number(linear.offset);
  }
  expr() {
    const model = this.vars[0]?.model ?? null, terms = /* @__PURE__ */ new Map();
    for (let index = 0; index < this.vars.length; index += 1)
      terms.set(this.vars[index].index, this.coeffs[index]);
    return new LinearExpr(model, terms, this.offset);
  }
  plus(value) {
    return this.expr().plus(value);
  }
  minus(value) {
    return this.expr().minus(value);
  }
  times(coeff) {
    return this.expr().times(coeff);
  }
  toString() {
    return formatFlatExpression(this.vars, this.coeffs, this.offset);
  }
  repr() {
    return `FlatFloatExpr([${this.vars.map((variable) => variable.repr()).join(", ")}], [${this.coeffs.join(", ")}], ${this.offset})`;
  }
}
class IntervalVar {
  constructor(model, index, name = "", start, size, end, isPresent) {
    __publicField(this, "model", model);
    __publicField(this, "index", index);
    __publicField(this, "name", name);
    __publicField(this, "start", start);
    __publicField(this, "size", size);
    __publicField(this, "end", end);
    __publicField(this, "isPresent", isPresent);
  }
  get model_proto() {
    return this.model.proto();
  }
  startExpr() {
    return this.start;
  }
  sizeExpr() {
    return this.size;
  }
  endExpr() {
    return this.end;
  }
  presenceLiterals() {
    return this.isPresent === void 0 ? [] : [this.isPresent];
  }
  toString() {
    return this.name || `interval${this.index}`;
  }
  repr() {
    const pieces = [
      `start = ${this.start}`,
      `size = ${this.size}`,
      `end = ${this.end}`
    ];
    return this.isPresent !== void 0 && pieces.push(`is_present = ${this.isPresent}`), `${this}(${pieces.join(", ")})`;
  }
}
class Constraint {
  constructor(model, index) {
    __publicField(this, "model", model);
    __publicField(this, "index", index);
  }
  get name() {
    return this.model.proto().constraints?.[this.index]?.name ?? "";
  }
  withName(name) {
    const constraint = this.model.proto().constraints?.[this.index];
    return assert(constraint, "constraint no longer exists in model"), constraint.name = name, this;
  }
  with_name(name) {
    return this.withName(name);
  }
  onlyEnforceIf(literals, ...rest) {
    const values = literalList(literals, rest), constraint = this.model.proto().constraints?.[this.index];
    return assert(constraint, "constraint no longer exists in model"), constraint.enforcementLiteral = [
      ...constraint.enforcementLiteral ?? [],
      ...this.model.literalReferences(values)
    ], this;
  }
}
function simplifyLinearSum(values) {
  let constant = 0;
  const nonConstantValues = [];
  for (const value of values)
    typeof value == "number" ? constant += value : nonConstantValues.push(value);
  return nonConstantValues.length === 0 ? LinearExpr.constant(constant) : constant === 0 && nonConstantValues.length === 1 ? nonConstantValues[0] : null;
}
function combineLinearExpressions(values, scaleByIndex, display) {
  let model = null;
  const terms = /* @__PURE__ */ new Map();
  let offset = 0, index = 0;
  for (const value of values) {
    const scale = scaleByIndex?.(index) ?? 1;
    assert(Number.isFinite(scale), `expected finite coefficient, got ${scale}`);
    const expression = LinearExpr.from(value);
    model && expression.model && requireSameModel(model, expression.model, "linear expression"), model ?? (model = expression.model);
    for (const [termIndex, termCoeff] of expression.terms)
      mergeTerms(terms, termIndex, termCoeff * scale);
    offset += expression.offset * scale, index += 1;
  }
  return new LinearExpr(model, terms, offset, display ?? null);
}
function sum(values, ...rest) {
  const valueList = iterableValues(values, rest), simplified = simplifyLinearSum(valueList);
  if (simplified !== null)
    return simplified;
  const displayValues = valueList.map((value) => LinearExpr.from(value).displayNodeForRendering());
  return combineLinearExpressions(valueList, void 0, { kind: "sum", values: displayValues });
}
function weightedSum(values, coeffs) {
  const valueList = Array.from(values), coeffList = Array.from(coeffs);
  valueError(valueList.length === coeffList.length, "weightedSum requires the same number of expressions and coefficients");
  const displayValues = valueList.map((value) => LinearExpr.from(value).displayNodeForRendering()), result = combineLinearExpressions(valueList, (index) => coeffList[index], {
    kind: "weighted",
    values: displayValues,
    coeffs: coeffList
  }), simplified = simplifyLinearSum([result]);
  return simplified !== null ? simplified : result;
}
function term(variable, coeff) {
  return variable.times(coeff);
}
function formatFlatExpression(vars, coeffs, offset) {
  const pieces = [];
  for (let index = 0; index < vars.length; index += 1) {
    const coeff = coeffs[index], variable = String(vars[index]);
    coeff === 1 ? pieces.push(variable) : coeff === -1 ? pieces.push(`-${variable}`) : pieces.push(`${coeff} * ${variable}`);
  }
  (offset !== 0 || pieces.length === 0) && pieces.push(String(offset));
  const [first, ...rest] = pieces, value = rest.reduce((text, piece) => piece.startsWith("-") ? `${text} - ${piece.slice(1)}` : `${text} + ${piece}`, first);
  return pieces.length > 1 ? `(${value})` : value;
}
function formatDomain(domain) {
  const pieces = [];
  for (let index = 0; index < domain.length; index += 2) {
    const lower = domain[index], upper = domain[index + 1];
    if (upper === void 0)
      break;
    const lowerText = protoInt64ToString(lower), upperText = protoInt64ToString(upper);
    pieces.push(lowerText === upperText ? lowerText : `${lowerText}..${upperText}`);
  }
  return pieces.join(", ");
}
function isBooleanDomain(domain) {
  return domain.length === 2 && compareProtoInt64(domain[0], 0) >= 0 && compareProtoInt64(domain[1], 1) <= 0;
}
class Domain {
  constructor(lowerOrIntervals, upper) {
    __publicField(this, "flatIntervals");
    if (upper !== void 0) {
      this.flatIntervals = [normalizeInt64(lowerOrIntervals), normalizeInt64(upper)];
      return;
    }
    if (typeof lowerOrIntervals == "number" || typeof lowerOrIntervals == "string" || isProtoInt64Object(lowerOrIntervals)) {
      const value = normalizeInt64(lowerOrIntervals);
      this.flatIntervals = [value, value];
      return;
    }
    this.flatIntervals = Array.from(lowerOrIntervals, normalizeInt64);
  }
  static fromFlatIntervals(intervals) {
    return new Domain(Array.from(intervals, normalizeInt64));
  }
  static from_flat_intervals(intervals) {
    return Domain.fromFlatIntervals(intervals);
  }
  static fromIntervals(intervals) {
    const flatIntervals = [];
    for (const interval of intervals) {
      const values = Array.from(interval, normalizeInt64);
      valueError(values.length === 1 || values.length === 2, "domain intervals must contain one or two bounds"), flatIntervals.push(values[0], values[1] ?? values[0]);
    }
    return new Domain(flatIntervals);
  }
  static from_intervals(intervals) {
    return Domain.fromIntervals(intervals);
  }
  static fromValues(values) {
    const sortedValues = Array.from(new Set(values)).sort((left, right) => left - right), flatIntervals = [];
    for (const value of sortedValues) {
      valueError(Number.isInteger(value), `domain value must be an integer, got ${value}`);
      const lastUpper = flatIntervals[flatIntervals.length - 1];
      typeof lastUpper == "number" && lastUpper + 1 === value ? flatIntervals[flatIntervals.length - 1] = value : flatIntervals.push(value, value);
    }
    return new Domain(flatIntervals);
  }
  static from_values(values) {
    return Domain.fromValues(values);
  }
}
class CpModel {
  constructor(model) {
    __publicField(this, "model");
    __publicField(this, "boolVariableIndexes", /* @__PURE__ */ new Set());
    __publicField(this, "constantIndexes", /* @__PURE__ */ new Map());
    __publicField(this, "intVariables", /* @__PURE__ */ new Map());
    __publicField(this, "trueConstant", null);
    __publicField(this, "falseConstant", null);
    this.model = model === void 0 ? { variables: [], constraints: [] } : cloneProto(model);
    for (const [index, variable] of (this.model.variables ?? []).entries()) {
      const domain = variable.domain ?? [];
      isBooleanDomain(domain) && this.boolVariableIndexes.add(index), domain.length === 2 && compareProtoInt64(domain[0], domain[1]) === 0 && this.constantIndexes.set(protoInt64ToNumber(domain[0]), index);
    }
  }
  get name() {
    return this.model.name ?? "";
  }
  set name(name) {
    this.model.name = name;
  }
  proto() {
    return this.model;
  }
  Proto() {
    return this.proto();
  }
  clone() {
    return new CpModel(this.model);
  }
  removeAllNames() {
    this.model.name = "";
    for (const variable of this.model.variables ?? [])
      variable.name = "";
    for (const constraint of this.model.constraints ?? [])
      constraint.name = "";
  }
  remove_all_names() {
    this.removeAllNames();
  }
  newIntVar(lb, ub, name = "") {
    const index = this.model.variables?.length ?? 0, domain = [normalizeInt64(lb), normalizeInt64(ub)];
    this.model.variables?.push(compareProtoInt64(lb, ub) <= 0 ? { name, domain } : { name }), isBooleanDomain(domain) && this.boolVariableIndexes.add(index);
    const variable = new IntVar(this, index, name);
    return this.intVariables.set(index, variable), variable;
  }
  new_int_var(lb, ub, name = "") {
    return this.newIntVar(lb, ub, name);
  }
  NewIntVar(lb, ub, name = "") {
    return this.newIntVar(lb, ub, name);
  }
  newIntVarFromDomain(domain, name = "") {
    const index = this.model.variables?.length ?? 0, flatDomain = [...domain.flatIntervals];
    this.model.variables?.push({ name, domain: flatDomain }), isBooleanDomain(flatDomain) && this.boolVariableIndexes.add(index);
    const variable = new IntVar(this, index, name);
    return this.intVariables.set(index, variable), variable;
  }
  new_int_var_from_domain(domain, name = "") {
    return this.newIntVarFromDomain(domain, name);
  }
  NewIntVarFromDomain(domain, name = "") {
    return this.newIntVarFromDomain(domain, name);
  }
  newBoolVar(name = "") {
    const index = this.model.variables?.length ?? 0;
    this.model.variables?.push({ name, domain: [0, 1] }), this.boolVariableIndexes.add(index);
    const variable = new BoolVar(this, index, name);
    return this.intVariables.set(index, variable), variable;
  }
  new_bool_var(name = "") {
    return this.newBoolVar(name);
  }
  NewBoolVar(name = "") {
    return this.newBoolVar(name);
  }
  newConstant(value, name = "") {
    return name ? this.newIntVar(value, value, name) : this.getIntVarFromProtoIndex(this.getOrMakeIndexFromConstant(value));
  }
  new_constant(value, name = "") {
    return this.newConstant(value, name);
  }
  NewConstant(value, name = "") {
    return this.newConstant(value, name);
  }
  getIntVarFromProtoIndex(index) {
    valueError(Number.isInteger(index), `variable index must be an integer, got ${index}`);
    const variables = this.model.variables ?? [];
    valueError(index >= 0 && index < variables.length, `getIntVarFromProtoIndex: out of bound index ${index}`);
    const existing = this.intVariables.get(index);
    if (existing !== void 0)
      return existing;
    const variable = new IntVar(this, index, variables[index]?.name ?? "");
    return this.intVariables.set(index, variable), variable;
  }
  get_int_var_from_proto_index(index) {
    return this.getIntVarFromProtoIndex(index);
  }
  getBoolVarFromProtoIndex(index) {
    const variable = this.getIntVarFromProtoIndex(index);
    if (!variable.isBoolean())
      throw new TypeError(`getBoolVarFromProtoIndex: index ${index} is not Boolean`);
    if (variable instanceof BoolVar)
      return variable;
    const boolVariable = new BoolVar(this, index);
    return this.intVariables.set(index, boolVariable), boolVariable;
  }
  get_bool_var_from_proto_index(index) {
    return this.getBoolVarFromProtoIndex(index);
  }
  getIntervalVarFromProtoIndex(index) {
    valueError(Number.isInteger(index), `interval index must be an integer, got ${index}`);
    const constraints = this.model.constraints ?? [];
    valueError(index >= 0 && index < constraints.length, `getIntervalVarFromProtoIndex: out of bound index ${index}`);
    const constraint = constraints[index];
    valueError(constraint?.interval !== void 0, `getIntervalVarFromProtoIndex: index ${index} is not an interval`);
    const interval = constraint.interval;
    return new IntervalVar(
      this,
      index,
      constraint.name ?? "",
      this.expressionFromProto(interval.start),
      this.expressionFromProto(interval.size),
      this.expressionFromProto(interval.end),
      constraint.enforcementLiteral?.[0] === void 0 ? void 0 : this.literalFromProtoIndex(constraint.enforcementLiteral[0])
    );
  }
  get_interval_var_from_proto_index(index) {
    return this.getIntervalVarFromProtoIndex(index);
  }
  getOrMakeIndexFromConstant(value) {
    valueError(Number.isInteger(value), `constant index requires an integer, got ${value}`);
    const existingIndex = this.constantIndexes.get(value);
    if (existingIndex !== void 0)
      return existingIndex;
    const index = this.model.variables?.length ?? 0, domain = [value, value];
    return this.model.variables?.push({ domain }), isBooleanDomain(domain) && this.boolVariableIndexes.add(index), this.constantIndexes.set(value, index), index;
  }
  get_or_make_index_from_constant(value) {
    return this.getOrMakeIndexFromConstant(value);
  }
  getOrMakeVariableIndex(variable) {
    return this.get_or_make_variable_index(variable);
  }
  isBooleanValue(value) {
    return value === !0 || value === !1;
  }
  is_boolean_value(value) {
    return this.isBooleanValue(value);
  }
  isBooleanIndex(index) {
    return this.boolVariableIndexes.has(index);
  }
  get_or_make_variable_index(variable) {
    if (typeof variable == "number")
      return valueError(Number.isInteger(variable), `variable index requires an integer, got ${variable}`), this.getOrMakeIndexFromConstant(variable);
    if (variable instanceof IntVar)
      return requireSameModel(this, variable.model, "variable"), variable.index;
    if (variable instanceof NotBoolVar)
      return requireSameModel(this, variable.model, "variable"), variable.index;
    if (variable === !0)
      return this.constantBoolIndex(!0);
    if (variable === !1)
      return this.constantBoolIndex(!1);
    throw new TypeError("expected a variable-like object");
  }
  add(bound) {
    return bound === !0 ? this.addBoolOr([!0]) : bound === !1 ? this.addBoolOr([]) : this.addLinearConstraint(bound.expression, bound.lowerBound, bound.upperBound, bound.domain);
  }
  Add(bound) {
    return this.add(bound);
  }
  addLinearConstraint(expression, lb, ub, domain) {
    const expr = LinearExpr.from(expression);
    if (this.checkExpressionModel(expr), expr.terms.size === 0 && domain === void 0) {
      const numericLb = protoInt64ToNumber(lb), numericUb = protoInt64ToNumber(ub);
      return expr.offset >= numericLb && expr.offset <= numericUb ? this.pushConstraint({ boolAnd: { literals: [] } }) : this.pushConstraint({ boolOr: { literals: [] } });
    }
    const proto = expr.toProto(), adjustedDomain = (domain ?? [lb, ub]).map((value) => adjustDomainEndpoint(value, expr.offset));
    return this.pushConstraint({
      linear: {
        vars: proto.vars,
        coeffs: proto.coeffs,
        domain: adjustedDomain
      }
    });
  }
  add_linear_constraint(expression, lb, ub) {
    return this.addLinearConstraint(expression, lb, ub);
  }
  AddLinearConstraint(expression, lb, ub) {
    return this.addLinearConstraint(expression, lb, ub);
  }
  addEquality(left, right) {
    return this.add(LinearExpr.from(left).eq(right));
  }
  addAllDifferent(expressions, ...rest) {
    return this.pushConstraint({
      allDiff: { exprs: this.expressionProtos(expressionList(expressions, rest)) }
    });
  }
  AddAllDifferent(expressions, ...rest) {
    return this.addAllDifferent(expressions, ...rest);
  }
  addElement(index, expressions, target) {
    const exprs = Array.from(expressions);
    return valueError(exprs.length > 0, "addElement requires at least one expression"), typeof index == "number" ? (valueError(Number.isInteger(index), `element index must be an integer, got ${index}`), valueError(index >= 0 && index < exprs.length, `element index ${index} is out of range`), this.add(LinearExpr.from(target).eq(exprs[index]))) : this.pushConstraint({
      element: {
        linearIndex: this.expressionProto(index),
        exprs: this.expressionProtos(exprs),
        linearTarget: this.expressionProto(target)
      }
    });
  }
  addAllowedAssignments(expressions, tuples) {
    const exprs = this.expressionProtos(expressions);
    valueError(exprs.length > 0, "addAllowedAssignments requires at least one expression");
    const values = Array.from(tuples, (tupleValue) => Array.from(tupleValue));
    for (const tupleValue of values)
      valueError(tupleValue.length === exprs.length, "tuple arity does not match expression count");
    return this.pushConstraint({
      table: {
        exprs,
        values: values.flat().map(asInt64)
      }
    });
  }
  addForbiddenAssignments(expressions, tuples) {
    const constraint = this.addAllowedAssignments(expressions, tuples), proto = this.model.constraints?.[constraint.index];
    return assert(proto?.table, "table constraint was not created"), proto.table.negated = !0, constraint;
  }
  addAutomaton(expressions, startingState, finalStates, transitions) {
    const exprs = this.expressionProtos(expressions), finalStateValues = Array.from(finalStates, asInt64), transitionValues = Array.from(transitions);
    valueError(exprs.length > 0, "addAutomaton requires at least one expression"), valueError(finalStateValues.length > 0, "addAutomaton requires at least one final state"), valueError(transitionValues.length > 0, "addAutomaton requires at least one transition");
    const tails = [], labels = [], heads = [];
    for (const transition of transitionValues) {
      valueError(transition.length === 3, "automaton transitions must contain tail, label, and head");
      const [tail, label, head] = transition;
      tails.push(asInt64(tail)), labels.push(asInt64(label)), heads.push(asInt64(head));
    }
    return this.pushConstraint({
      automaton: {
        exprs,
        startingState: asInt64(startingState),
        finalStates: finalStateValues,
        transitionTail: tails,
        transitionLabel: labels,
        transitionHead: heads
      }
    });
  }
  addCircuit(arcs) {
    const arcValues = Array.from(arcs);
    valueError(arcValues.length > 0, "addCircuit requires at least one arc");
    const tails = [], heads = [], literals = [];
    for (const [tail, head, literal] of arcValues) {
      const [literalRef] = this.literalReferences([literal]);
      tails.push(tail), heads.push(head), literals.push(literalRef);
    }
    return this.pushConstraint({ circuit: { tails, heads, literals } });
  }
  addMultipleCircuit(arcs) {
    const arcValues = Array.from(arcs);
    valueError(arcValues.length > 0, "addMultipleCircuit requires at least one arc");
    const tails = [], heads = [], literals = [];
    for (const [tail, head, literal] of arcValues) {
      const [literalRef] = this.literalReferences([literal]);
      tails.push(tail), heads.push(head), literals.push(literalRef);
    }
    return this.pushConstraint({ routes: { tails, heads, literals } });
  }
  addInverse(direct, inverse) {
    return this.pushConstraint({
      inverse: {
        fDirect: this.variableIndexes(direct),
        fInverse: this.variableIndexes(inverse)
      }
    });
  }
  addMaxEquality(target, expressions, ...rest) {
    return this.pushConstraint({
      linMax: {
        target: this.expressionProto(target),
        exprs: this.expressionProtos(expressionList(expressions, rest))
      }
    });
  }
  add_max_equality(target, expressions, ...rest) {
    return this.addMaxEquality(target, expressions, ...rest);
  }
  addMinEquality(target, expressions, ...rest) {
    const values = expressionList(expressions, rest);
    return this.pushConstraint({
      linMax: {
        target: LinearExpr.from(target).neg().toProto(),
        exprs: values.map((expression) => LinearExpr.from(expression).neg().toProto())
      }
    });
  }
  add_min_equality(target, expressions, ...rest) {
    return this.addMinEquality(target, expressions, ...rest);
  }
  addAbsEquality(target, expression) {
    const expr = LinearExpr.from(expression);
    return this.addMaxEquality(target, [expr, expr.neg()]);
  }
  add_abs_equality(target, expression) {
    return this.addAbsEquality(target, expression);
  }
  addDivisionEquality(target, numerator, denominator) {
    return this.pushConstraint({
      intDiv: {
        target: this.expressionProto(target),
        exprs: [this.expressionProto(numerator), this.expressionProto(denominator)]
      }
    });
  }
  add_division_equality(target, numerator, denominator) {
    return this.addDivisionEquality(target, numerator, denominator);
  }
  addModuloEquality(target, expression, modulo) {
    return this.pushConstraint({
      intMod: {
        target: this.expressionProto(target),
        exprs: [this.expressionProto(expression), this.expressionProto(modulo)]
      }
    });
  }
  add_modulo_equality(target, expression, modulo) {
    return this.addModuloEquality(target, expression, modulo);
  }
  addMultiplicationEquality(target, expressions, ...rest) {
    return this.pushConstraint({
      intProd: {
        target: this.expressionProto(target),
        exprs: this.expressionProtos(expressionList(expressions, rest))
      }
    });
  }
  add_multiplication_equality(target, expressions, ...rest) {
    return this.addMultiplicationEquality(target, expressions, ...rest);
  }
  addImplication(left, right) {
    return this.pushConstraint({
      enforcementLiteral: this.literalReferences([left]),
      boolAnd: { literals: this.literalReferences([right]) }
    });
  }
  add_implication(left, right) {
    return this.addImplication(left, right);
  }
  addBoolOr(literals, ...rest) {
    return this.pushConstraint({ boolOr: { literals: this.literalReferences(literalList(literals, rest)) } });
  }
  add_bool_or(literals, ...rest) {
    return this.addBoolOr(literals, ...rest);
  }
  AddBoolOr(literals, ...rest) {
    return this.addBoolOr(literals, ...rest);
  }
  addAtLeastOne(literals, ...rest) {
    return this.addBoolOr(literals, ...rest);
  }
  add_at_least_one(literals, ...rest) {
    return this.addAtLeastOne(literals, ...rest);
  }
  addBoolAnd(literals) {
    return this.pushConstraint({ boolAnd: { literals: this.literalReferences(literals) } });
  }
  add_bool_and(literals) {
    return this.addBoolAnd(literals);
  }
  AddBoolAnd(literals) {
    return this.addBoolAnd(literals);
  }
  addBoolXor(literals) {
    return this.pushConstraint({ boolXor: { literals: this.literalReferences(literals) } });
  }
  add_bool_xor(literals) {
    return this.addBoolXor(literals);
  }
  AddBoolXOr(literals) {
    return this.addBoolXor(literals);
  }
  addAtMostOne(literals) {
    return this.pushConstraint({ atMostOne: { literals: this.literalReferences(literals) } });
  }
  add_at_most_one(literals) {
    return this.addAtMostOne(literals);
  }
  addExactlyOne(literals) {
    return this.pushConstraint({ exactlyOne: { literals: this.literalReferences(literals) } });
  }
  add_exactly_one(literals) {
    return this.addExactlyOne(literals);
  }
  addMapDomain(variable, booleanVariables, offset = 0) {
    requireSameModel(this, variable.model, "map domain variable");
    for (const [index, literal] of Array.from(booleanVariables).entries()) {
      requireSameModel(this, literal.model, "map domain literal");
      const value = offset + index;
      this.pushConstraint({
        enforcementLiteral: [literal.index],
        linear: {
          vars: [variable.index],
          coeffs: [1],
          domain: [asInt64(value), asInt64(value)]
        }
      }), this.pushConstraint({
        enforcementLiteral: [literal.negated().index],
        linear: {
          vars: [variable.index],
          coeffs: [1],
          domain: [INT64_MIN, asInt64(value - 1), asInt64(value + 1), INT64_MAX]
        }
      });
    }
  }
  add_map_domain(variable, booleanVariables, offset = 0) {
    return this.addMapDomain(variable, booleanVariables, offset);
  }
  newIntervalVar(start, size, end, name = "") {
    return this.pushInterval({ start, size, end, name });
  }
  new_interval_var(start, size, end, name = "") {
    return this.newIntervalVar(start, size, end, name);
  }
  newFixedSizeIntervalVar(start, size, name = "") {
    return this.pushInterval({ start, size, end: LinearExpr.from(start).plus(size), name });
  }
  new_fixed_size_interval_var(start, size, name = "") {
    return this.newFixedSizeIntervalVar(start, size, name);
  }
  newOptionalFixedSizeIntervalVar(start, size, isPresent, name = "") {
    return this.newOptionalIntervalVar(start, size, LinearExpr.from(start).plus(size), isPresent, name);
  }
  new_optional_fixed_size_interval_var(start, size, isPresent, name = "") {
    return this.newOptionalFixedSizeIntervalVar(start, size, isPresent, name);
  }
  newOptionalIntervalVar(start, size, end, isPresent, name = "") {
    if (!(isPresent instanceof BoolVar || isPresent instanceof NotBoolVar || typeof isPresent == "boolean" || isPresent === 0 || isPresent === 1))
      throw new TypeError("optional interval presence literal must be Boolean");
    if (this.hasBooleanExpressionTerm(start) || this.hasBooleanExpressionTerm(size) || this.hasBooleanExpressionTerm(end))
      throw new TypeError("optional interval start, size, and end must be integer expressions");
    return this.pushInterval({ start, size, end, isPresent, name });
  }
  new_optional_interval_var(start, size, end, isPresent, name = "") {
    return this.newOptionalIntervalVar(start, size, end, isPresent, name);
  }
  addNoOverlap(intervals) {
    return this.pushConstraint({ noOverlap: { intervals: this.intervalIndexes(intervals) } });
  }
  add_no_overlap(intervals) {
    return this.addNoOverlap(intervals);
  }
  AddNoOverlap(intervals) {
    return this.addNoOverlap(intervals);
  }
  addNoOverlap2D(xIntervals, yIntervals) {
    return this.pushConstraint({
      noOverlap2d: {
        xIntervals: this.intervalIndexes(xIntervals),
        yIntervals: this.intervalIndexes(yIntervals)
      }
    });
  }
  add_no_overlap_2d(xIntervals, yIntervals) {
    return this.addNoOverlap2D(xIntervals, yIntervals);
  }
  AddNoOverlap2D(xIntervals, yIntervals) {
    return this.addNoOverlap2D(xIntervals, yIntervals);
  }
  addCumulative(intervals, demands, capacity) {
    return this.pushConstraint({
      cumulative: {
        intervals: this.intervalIndexes(intervals),
        demands: this.expressionProtos(demands),
        capacity: this.expressionProto(capacity)
      }
    });
  }
  add_cumulative(intervals, demands, capacity) {
    return this.addCumulative(intervals, demands, capacity);
  }
  addReservoirConstraint(times, levelChanges, minLevel, maxLevel, activeLiterals) {
    return this.pushConstraint({
      reservoir: {
        timeExprs: this.expressionProtos(times),
        levelChanges: this.expressionProtos(levelChanges),
        minLevel: asInt64(minLevel),
        maxLevel: asInt64(maxLevel),
        activeLiterals: activeLiterals ? this.literalReferences(activeLiterals) : void 0
      }
    });
  }
  addDecisionStrategy(expressions, variableSelectionStrategy, domainReductionStrategy) {
    var _a;
    (_a = this.model).searchStrategy ?? (_a.searchStrategy = []), this.model.searchStrategy.push({
      exprs: this.expressionProtos(expressions),
      variableSelectionStrategy,
      domainReductionStrategy
    });
  }
  addHint(variable, value) {
    var _a;
    const hintedValue = typeof value == "boolean" ? value ? 1 : 0 : value, hintVariable = variable instanceof NotBoolVar ? variable.variable : variable, hintValue = variable instanceof NotBoolVar ? 1 - hintedValue : hintedValue;
    requireSameModel(this, hintVariable.model, "hint variable"), (_a = this.model).solutionHint ?? (_a.solutionHint = { vars: [], values: [] }), this.model.solutionHint.vars?.push(hintVariable.index), this.model.solutionHint.values?.push(asInt64(hintValue));
  }
  addAssumption(literal) {
    var _a;
    (_a = this.model).assumptions ?? (_a.assumptions = []);
    const index = literalIndex(literal);
    assert(typeof index == "number", "assumptions require variable literals"), this.model.assumptions.push(index);
  }
  addAssumptions(literals) {
    for (const literal of literals)
      this.addAssumption(literal);
  }
  clearAssumptions() {
    this.model.assumptions = [];
  }
  minimize(expression) {
    const expr = LinearExpr.from(expression);
    if (this.checkExpressionModel(expr), expr.hasFloatingPointTerms()) {
      this.model.objective = void 0, this.model.floatingPointObjective = expr.toFloatObjective(!1);
      return;
    }
    const proto = expr.toProto();
    this.model.floatingPointObjective = void 0, this.model.objective = {
      vars: proto.vars,
      coeffs: proto.coeffs,
      offset: typeof proto.offset == "number" ? proto.offset : void 0
    };
  }
  Minimize(expression) {
    return this.minimize(expression);
  }
  maximize(expression) {
    const originalExpr = LinearExpr.from(expression);
    if (this.checkExpressionModel(originalExpr), originalExpr.hasFloatingPointTerms()) {
      this.model.objective = void 0, this.model.floatingPointObjective = originalExpr.toFloatObjective(!0);
      return;
    }
    const expr = originalExpr.neg();
    this.checkExpressionModel(expr);
    const proto = expr.toProto();
    this.model.floatingPointObjective = void 0, this.model.objective = {
      vars: proto.vars,
      coeffs: proto.coeffs,
      offset: typeof proto.offset == "number" ? proto.offset : void 0,
      scalingFactor: -1
    };
  }
  Maximize(expression) {
    return this.maximize(expression);
  }
  hasObjective() {
    return this.model.objective !== void 0 || this.model.floatingPointObjective !== void 0;
  }
  modelStats() {
    return JSON.stringify({
      variables: this.model.variables?.length ?? 0,
      constraints: this.model.constraints?.length ?? 0,
      hasObjective: this.hasObjective()
    });
  }
  async validate() {
    const modelBytes = await CpSat.createModel(this.proto()), validation = await CpSat.validate(modelBytes);
    return validation.ok ? "" : validation.message;
  }
  pushInterval(input) {
    const constraint = {
      name: input.name,
      interval: {
        start: this.expressionProto(input.start),
        size: this.expressionProto(input.size),
        end: this.expressionProto(input.end)
      }
    };
    input.isPresent !== void 0 && (constraint.enforcementLiteral = this.literalReferences([input.isPresent]));
    const index = this.model.constraints?.length ?? 0;
    return this.model.constraints?.push(constraint), new IntervalVar(this, index, input.name, input.start, input.size, input.end, input.isPresent);
  }
  pushConstraint(constraint) {
    const index = this.model.constraints?.length ?? 0;
    return this.model.constraints?.push(constraint), new Constraint(this, index);
  }
  checkExpressionModel(expression) {
    expression.model && requireSameModel(this, expression.model, "linear expression");
  }
  expressionProto(expression) {
    const expr = LinearExpr.from(expression);
    return this.checkExpressionModel(expr), expr.toProto();
  }
  expressionFromProto(proto) {
    if (proto === void 0)
      return 0;
    const terms = /* @__PURE__ */ new Map(), vars = proto.vars ?? [], coeffs = proto.coeffs ?? [];
    for (let index = 0; index < vars.length; index += 1)
      mergeTerms(terms, vars[index], protoInt64ToNumber(coeffs[index]));
    return new LinearExpr(this, terms, protoInt64ToNumber(proto.offset));
  }
  literalFromProtoIndex(index) {
    return index >= 0 ? this.getBoolVarFromProtoIndex(index) : this.getBoolVarFromProtoIndex(-index - 1).negated();
  }
  expressionProtos(expressions) {
    return Array.from(expressions, (expression) => this.expressionProto(expression));
  }
  variableIndexes(variables) {
    return Array.from(variables, (variable) => (requireSameModel(this, variable.model, "variable"), variable.index));
  }
  intervalIndexes(intervals) {
    return Array.from(intervals, (interval) => {
      if (!(interval instanceof IntervalVar))
        throw new TypeError("expected interval variable");
      return requireSameModel(this, interval.model, "interval"), interval.index;
    });
  }
  hasBooleanExpressionTerm(expression) {
    if (isBoolExpression(expression))
      return !0;
    const expr = LinearExpr.from(expression);
    return this.checkExpressionModel(expr), Array.from(expr.terms.keys()).some((index) => this.boolVariableIndexes.has(index));
  }
  literalReferences(literals) {
    return Array.from(literals, (literal) => {
      const index = literalIndex(literal);
      return index === !0 ? this.constantBoolIndex(!0) : index === !1 ? this.constantBoolIndex(!1) : (assert(literal instanceof BoolVar || literal instanceof NotBoolVar, "literal must be a Boolean variable or its negation"), requireSameModel(this, literal.model, "literal"), index);
    });
  }
  constantBoolIndex(value) {
    return value ? (this.trueConstant ?? (this.trueConstant = this.getBoolVarFromProtoIndex(this.getOrMakeIndexFromConstant(1))), this.trueConstant.index) : (this.falseConstant ?? (this.falseConstant = this.getBoolVarFromProtoIndex(this.getOrMakeIndexFromConstant(0))), this.falseConstant.index);
  }
}
class CpSolverSolutionCallback {
  constructor() {
    __publicField(this, "currentResponse", null);
  }
  onSolutionCallback() {
  }
  value(expression) {
    return evaluateLinearExpression(this.requireCurrentResponse(), expression);
  }
  floatValue(expression) {
    return evaluateLinearExpression(this.requireCurrentResponse(), expression);
  }
  booleanValue(literal) {
    return evaluateBooleanLiteral(this.requireCurrentResponse(), literal);
  }
  get objectiveValue() {
    const response = this.requireCurrentResponse();
    return runtimeError(typeof response.objectiveValue == "number", "missing objective value"), response.objectiveValue;
  }
  get bestObjectiveBound() {
    const response = this.requireCurrentResponse();
    return runtimeError(typeof response.bestObjectiveBound == "number", "missing best objective bound"), response.bestObjectiveBound;
  }
  get wallTime() {
    return this.requireCurrentResponse().wallTime ?? 0;
  }
  _run(response) {
    this.currentResponse = response;
    try {
      this.onSolutionCallback();
    } finally {
      this.currentResponse = null;
    }
  }
  requireCurrentResponse() {
    if (!this.currentResponse)
      throw new RuntimeError("solve() has not started or the callback is not currently running");
    return this.currentResponse;
  }
}
class CpSolver {
  constructor() {
    __publicField(this, "lastResponse", null);
    __publicField(this, "parameters", {});
    __publicField(this, "bestBoundCallback", null);
    __publicField(this, "logCallback", null);
  }
  async solve(model, params = null, callbacks = {}) {
    const solutionCallback = params instanceof CpSolverSolutionCallback ? params : null, solveParams = solutionCallback ? this.parameters : params, mergedParams = solveParams instanceof Uint8Array ? solveParams : { ...this.parameters, ...solveParams ?? {} }, modelBytes = await CpSat.createModel(model.proto()), result = await CpSat.solve(modelBytes, mergedParams, {
      ...callbacks,
      onSolution: solutionCallback || callbacks.onSolution ? (response, bytes) => {
        solutionCallback?._run(response), callbacks.onSolution?.(response, bytes);
      } : void 0,
      onBestBound: this.bestBoundCallback || callbacks.onBestBound ? (bound) => {
        this.bestBoundCallback?.(bound), callbacks.onBestBound?.(bound);
      } : void 0,
      onLog: this.logCallback || callbacks.onLog ? (message) => {
        this.logCallback?.(message), callbacks.onLog?.(message);
      } : void 0
    });
    return this.lastResponse = result.response, result.response?.status;
  }
  response() {
    return this.lastResponse;
  }
  responseStats() {
    return JSON.stringify(this.requireResponse());
  }
  get best_objective_bound() {
    return this.bestObjectiveBound();
  }
  get deterministic_time() {
    const response = this.requireResponse();
    return runtimeError(typeof response.deterministicTime == "number", "missing deterministic time"), response.deterministicTime;
  }
  get num_binary_propagations() {
    return protoInt64ToNumber(this.requireResponse().numBinaryPropagations);
  }
  get num_integer_propagations() {
    return protoInt64ToNumber(this.requireResponse().numIntegerPropagations);
  }
  get user_time() {
    const response = this.requireResponse();
    return runtimeError(typeof response.userTime == "number", "missing user time"), response.userTime;
  }
  get response_proto() {
    return this.requireResponse();
  }
  get solve_log() {
    return this.requireResponse().solveLog;
  }
  get num_booleans() {
    return this.numBooleans;
  }
  get num_conflicts() {
    return this.numConflicts;
  }
  get num_branches() {
    return this.numBranches;
  }
  get num_integers() {
    return protoInt64ToNumber(this.requireResponse().numIntegers);
  }
  get wall_time() {
    return this.wallTime;
  }
  get objective_value() {
    return this.objectiveValue();
  }
  set best_bound_callback(callback) {
    this.bestBoundCallback = callback;
  }
  set log_callback(callback) {
    this.logCallback = callback;
  }
  solutionInfo() {
    return this.requireResponse().solutionInfo ?? "";
  }
  get numBooleans() {
    return protoInt64ToNumber(this.requireResponse().numBooleans);
  }
  get numConflicts() {
    return protoInt64ToNumber(this.requireResponse().numConflicts);
  }
  get numBranches() {
    return protoInt64ToNumber(this.requireResponse().numBranches);
  }
  get wallTime() {
    return this.requireResponse().wallTime ?? 0;
  }
  value(expression) {
    return evaluateLinearExpression(this.requireResponse(), expression);
  }
  floatValue(expression) {
    return this.value(expression);
  }
  booleanValue(literal) {
    return evaluateBooleanLiteral(this.requireResponse(), literal);
  }
  objectiveValue() {
    const response = this.requireResponse();
    return runtimeError(typeof response.objectiveValue == "number", "missing objective value"), response.objectiveValue;
  }
  bestObjectiveBound() {
    const response = this.requireResponse();
    return runtimeError(typeof response.bestObjectiveBound == "number", "missing best objective bound"), response.bestObjectiveBound;
  }
  statusName(status = this.lastResponse?.status) {
    return typeof status == "string" ? status : CpSolverStatus[status] ?? String(status);
  }
  requireResponse() {
    return runtimeError(this.lastResponse !== null, "solve() has not completed with a solver response"), this.lastResponse;
  }
  get best_bound_callback() {
    return this.bestBoundCallback;
  }
  get log_callback() {
    return this.logCallback;
  }
}
export {
  ArithmeticError,
  BoolVar,
  BoundedLinearExpr,
  BoundedLinearExpression,
  Constraint,
  CpModel,
  CpSolver,
  CpSolverSolutionCallback,
  Domain,
  FlatFloatExpr,
  FlatIntExpr,
  IntVar,
  IntervalVar,
  LinearExpr,
  NotBoolVar,
  NotImplementedError,
  RuntimeError,
  ValueError,
  objectIsAFalseLiteral,
  objectIsATrueLiteral,
  object_is_a_false_literal,
  object_is_a_true_literal,
  rebuildFromLinearExpressionProto,
  rebuild_from_linear_expression_proto,
  sum,
  term,
  weightedSum
};
