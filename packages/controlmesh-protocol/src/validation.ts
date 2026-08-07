import Ajv2020, { type ErrorObject, type ValidateFunction } from "ajv/dist/2020.js";

import { controlmeshSchemas } from "./validators/schemas";

export type ControlMeshSchemaName = keyof typeof controlmeshSchemas;

export class ProtocolValidationError extends Error {
  readonly schemaName: ControlMeshSchemaName;
  readonly errors: ErrorObject[];

  constructor(schemaName: ControlMeshSchemaName, errors: ErrorObject[] = []) {
    super(`Response does not match ${schemaName}`);
    this.name = "ProtocolValidationError";
    this.schemaName = schemaName;
    this.errors = errors;
  }
}

const ajv = new Ajv2020({ allErrors: true, strict: false });
const validators = new Map<ControlMeshSchemaName, ValidateFunction>();

for (const schema of Object.values(controlmeshSchemas)) {
  ajv.addSchema(schema);
}

for (const [schemaName, schema] of Object.entries(controlmeshSchemas)) {
  const validate = ajv.getSchema(schema.$id);
  if (!validate) {
    throw new Error(`Unable to compile ${schemaName}`);
  }
  validators.set(schemaName as ControlMeshSchemaName, validate);
}

export function assertProtocolSchema<T>(
  schemaName: ControlMeshSchemaName,
  value: unknown,
): asserts value is T {
  const validate = validators.get(schemaName);
  if (!validate || !validate(value)) {
    throw new ProtocolValidationError(schemaName, validate?.errors ? [...validate.errors] : []);
  }
}
