import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import openapiTS, { astToString } from "openapi-typescript";

const input = process.env.OPENAPI_URL;
if (!input)
  throw new Error(
    "Set OPENAPI_URL to Aun’s published OpenAPI JSON URL before generating API types.",
  );
const url = new URL(input);
if (!["http:", "https:"].includes(url.protocol))
  throw new Error("OPENAPI_URL must use HTTP or HTTPS.");

const response = await fetch(url, { signal: AbortSignal.timeout(10_000) });
if (!response.ok)
  throw new Error(`OpenAPI download failed (${response.status}).`);
const schema = await response.json();
if (!schema || typeof schema !== "object" || !("openapi" in schema))
  throw new Error("The response is not an OpenAPI document.");

const ast = await openapiTS(schema);
const output = path.resolve("lib/generated/openapi.d.ts");
await mkdir(path.dirname(output), { recursive: true });
await writeFile(output, astToString(ast), "utf8");
process.stdout.write(`Generated TypeScript from ${url} at ${output}\n`);
