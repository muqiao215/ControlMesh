import Ajv2020 from "ajv/dist/2020.js";
import request from "../../../schemas/controlmesh/specmesh/specmesh-request.schema.json";
import result from "../../../schemas/controlmesh/specmesh/specmesh-result.schema.json";
import capabilities from "../../../schemas/controlmesh/specmesh/specmesh-capabilities.schema.json";

const validator = new Ajv2020({ strict: false });
const contracts = { request: validator.compile(request), result: validator.compile(result), capabilities: validator.compile(capabilities) };

/** External SpecMesh contracts stay independently versioned; reuse the existing validator. */
export function assertSpecMeshContract<T>(kind: keyof typeof contracts, value: unknown): asserts value is T {
  if (!contracts[kind](value)) throw new Error(`invalid_specmesh_${kind}`);
}
