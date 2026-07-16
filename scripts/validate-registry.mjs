#!/usr/bin/env node

import { readFile } from "node:fs/promises";

const REQUIRED_FIELDS = ["name", "url", "project_type", "declaration_file", "status"];
const URL_PREFIX = "https://github.com/quantskills/";

async function main() {
  const registryPath = process.argv[2] ?? "registry.json";
  let registry;

  try {
    registry = JSON.parse(await readFile(registryPath, "utf8"));
  } catch (error) {
    console.error(`无法读取或解析 ${registryPath}：${error.message}`);
    process.exitCode = 1;
    return;
  }

  const errors = [];
  if (!Array.isArray(registry)) {
    errors.push("registry.json 根节点必须是数组");
  } else {
    registry.forEach((entry, index) => {
      if (!isObject(entry)) {
        errors.push(`条目[${index}] 必须是对象`);
        return;
      }
      for (const field of REQUIRED_FIELDS) {
        if (typeof entry[field] !== "string" || entry[field].trim() === "") {
          errors.push(`条目[${index}].${field} 必须是非空 string`);
        }
      }
      if (
        typeof entry.url === "string" &&
        (!entry.url.startsWith(URL_PREFIX) || entry.url.length === URL_PREFIX.length)
      ) {
        errors.push(`条目[${index}].url 必须以 ${URL_PREFIX} 开头并包含仓库名`);
      }
    });
  }

  if (errors.length > 0) {
    errors.forEach((error) => console.error(`错误：${error}`));
    process.exitCode = 1;
    return;
  }
  console.log(`registry.json 校验通过，共 ${registry.length} 个条目。`);
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

await main();
