#!/usr/bin/env node
import { readFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const URL_PREFIX = "https://github.com/quantskills/";
const LEGACY_REQUIRED = ["name", "url", "project_type", "declaration_file", "status"];
const V2_REQUIRED = ["snapshot_id", "catalog", "workflow", "summary_zh", "summary_en", "interface", "category", "subcategory", "stage"];

function isObject(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function fallback(value) { return value === "uncategorized" || value === "unknown" || value === "fallback"; }

async function main() {
  const args = process.argv.slice(2);
  let contractMode = "audit";
  const modeIndex = args.indexOf("--contract-mode");
  if (modeIndex >= 0) {
    contractMode = args[modeIndex + 1];
    args.splice(modeIndex, 2);
  }
  if (!new Set(["audit", "enforce"]).has(contractMode)) throw new Error("--contract-mode must be audit or enforce");
  const registryPath = args[0] ?? "registry.json";
  const taxonomy = JSON.parse(await readFile(resolve(dirname(fileURLToPath(import.meta.url)), "..", "schema", "taxonomy.v1.json"), "utf8"));
  const categories = new Set(Object.keys(taxonomy.categories));
  const subcategories = new Set(Object.values(taxonomy.categories).flatMap(category => category.subcategories.map(item => item.id)));
  const stages = new Set(taxonomy.workflow_stages);
  const interfaceModes = new Set(["structured", "hybrid", "not-applicable"]);
  let registry;
  try { registry = JSON.parse(await readFile(registryPath, "utf8")); }
  catch (error) { console.error(`Unable to read ${registryPath}: ${error.message}`); process.exitCode = 1; return; }
  const errors = [], warnings = [], names = new Set(), snapshotIds = new Set();
  if (!Array.isArray(registry)) errors.push("registry root must be an array");
  else registry.forEach((entry, index) => {
    if (!isObject(entry)) { errors.push(`entry[${index}] must be an object`); return; }
    for (const field of LEGACY_REQUIRED) if (typeof entry[field] !== "string" || !entry[field].trim()) errors.push(`entry[${index}].${field} must be a nonempty string`);
    if (!names.add(entry.name)) errors.push(`duplicate asset name: ${entry.name}`);
    if (typeof entry.url === "string" && entry.url !== `${URL_PREFIX}${entry.name}`) errors.push(`entry[${index}].url must exactly match asset name`);
    const missing = V2_REQUIRED.filter(field => entry[field] === undefined || entry[field] === null || entry[field] === "");
    if (missing.length) (contractMode === "enforce" ? errors : warnings).push(`entry[${index}] missing v2 fields: ${missing.join(", ")}`);
    if (entry.snapshot_id !== undefined) {
      if (!/^sha256:[0-9a-f]{64}$/.test(entry.snapshot_id)) errors.push(`entry[${index}].snapshot_id is invalid`);
      else snapshotIds.add(entry.snapshot_id);
    }
    const v2Issues = [];
    if (entry.category !== undefined && !categories.has(entry.category)) v2Issues.push("unknown category");
    if (entry.subcategory !== undefined && !subcategories.has(entry.subcategory)) v2Issues.push("unknown subcategory");
    if (entry.stage !== undefined && !stages.has(entry.stage)) v2Issues.push("unknown stage");
    if (entry.catalog && (entry.catalog.category !== entry.category || entry.catalog.subcategory !== entry.subcategory)) v2Issues.push("catalog summary mismatch");
    if (entry.workflow && (entry.workflow.primary_stage !== entry.stage || !Array.isArray(entry.workflow.workflow_stages) || !entry.workflow.workflow_stages.every(stage => stages.has(stage)))) v2Issues.push("invalid workflow");
    if (entry.interface && !interfaceModes.has(entry.interface.mode)) v2Issues.push("unknown interface mode");
    if ([entry.summary_zh, entry.summary_en].some(value => fallback(value) || value === "待迁移")) v2Issues.push("fallback summary");
    if (entry.interface?.fallback || entry.workflow?.fallback || entry.catalog?.fallback) v2Issues.push("fallback marker");
    if (v2Issues.length) (contractMode === "enforce" ? errors : warnings).push(`entry[${index}] ${v2Issues.join(", ")}`);
  });
  if (contractMode === "enforce" && snapshotIds.size !== 1) errors.push("enforce mode requires one shared snapshot_id");
  if (warnings.length) console.warn(`warning: audit accepted ${warnings.length} legacy/fallback v2-field gaps`);
  if (errors.length) { errors.forEach(error => console.error(`error: ${error}`)); process.exitCode = 1; return; }
  console.log(`registry.json validation passed: ${registry.length} entries (${contractMode})`);
}
main().catch(error => { console.error(`error: ${error.message}`); process.exitCode = 1; });
