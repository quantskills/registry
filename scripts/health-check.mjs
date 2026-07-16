#!/usr/bin/env node

import { readFile, writeFile } from "node:fs/promises";

const MAX_BLOCK_BYTES = 16 * 1024;
const FIELD_TYPES = new Set(["text", "textarea", "select", "date", "number"]);
const RESERVED_KEYS = new Set(["task", "attachments"]);
const KEY_PATTERN = /^[a-z0-9_]{1,32}$/;
const FORM_PATTERN = /^```json qsh-form[ \t]*\r?\n([\s\S]*?)^```[ \t]*$/m;

async function main() {
  const registryPath = process.argv[2] ?? "registry.json";
  const outputPath = process.argv[3] ?? "health.md";
  const registry = JSON.parse(await readFile(registryPath, "utf8"));
  if (!Array.isArray(registry)) {
    throw new Error("registry.json 根节点必须是数组");
  }

  const results = [];
  for (const entry of registry) {
    results.push(await checkEntry(entry));
  }

  const generatedAt = process.env.HEALTH_DATE || new Date().toISOString();
  await writeFile(outputPath, renderHealth(results, generatedAt), "utf8");
  console.log(`已生成 ${outputPath}，共检查 ${results.length} 个条目。`);
}

async function checkEntry(entry) {
  const repository = repositoryPath(entry.url);
  const result = {
    name: entry.name,
    repositoryReachable: false,
    declarationExists: false,
    formFound: false,
    declarationValid: false,
    problems: [],
  };

  if (!repository) {
    result.problems.push("仓库 URL 无效");
    return result;
  }

  let lastResponse;
  for (const branch of ["main", "master"]) {
    const rawUrl = `https://raw.githubusercontent.com/${repository}/${branch}/${encodePath(entry.declaration_file)}`;
    try {
      lastResponse = await fetchWithTimeout(rawUrl);
      if (lastResponse.ok) {
        result.repositoryReachable = true;
        result.declarationExists = true;
        const source = await lastResponse.text();
        const validation = validateQshForm(source);
        result.formFound = validation.found;
        result.declarationValid = validation.errors.length === 0;
        if (!validation.found) {
          result.problems.push("未声明 qsh-form（可选增强）");
        }
        result.problems.push(...validation.errors);
        return result;
      }
      if (lastResponse.status !== 404) {
        result.repositoryReachable = true;
      }
    } catch (error) {
      result.problems.push(`${branch} 请求失败：${error.message}`);
    }
  }

  if (!result.repositoryReachable) {
    try {
      const repositoryResponse = await fetchWithTimeout(entry.url);
      result.repositoryReachable = repositoryResponse.ok;
    } catch (error) {
      result.problems.push(`仓库请求失败：${error.message}`);
    }
  }

  if (result.repositoryReachable) {
    result.problems.push("main 和 master 均无声明文件");
  } else {
    result.problems.push("仓库不可达");
  }
  return result;
}

async function fetchWithTimeout(url) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 8_000);
  try {
    return await fetch(url, {
      signal: controller.signal,
      headers: { "User-Agent": "quantskills-registry-health-check" },
    });
  } finally {
    clearTimeout(timeout);
  }
}

function repositoryPath(url) {
  const prefix = "https://github.com/";
  if (typeof url !== "string" || !url.startsWith(prefix)) {
    return null;
  }
  const path = url.slice(prefix.length).replace(/\/$/, "");
  return /^[^/]+\/[^/]+$/.test(path) ? path : null;
}

function encodePath(path) {
  return String(path)
    .split("/")
    .map((segment) => encodeURIComponent(segment))
    .join("/");
}

function validateQshForm(source) {
  const match = FORM_PATTERN.exec(source);
  if (!match) {
    return { found: false, errors: [] };
  }

  const errors = [];
  if (Buffer.byteLength(match[0], "utf8") > MAX_BLOCK_BYTES) {
    errors.push("qsh-form 整块超过 16KB");
  }

  let form;
  try {
    form = JSON.parse(match[1]);
  } catch (error) {
    return { found: true, errors: [...errors, `qsh-form JSON 非法：${error.message}`] };
  }
  if (!isObject(form)) {
    return { found: true, errors: [...errors, "qsh-form 根节点不是对象"] };
  }

  if (form.version !== 1) errors.push("version 不等于 1");
  if (form.task !== undefined) {
    if (!isObject(form.task)) {
      errors.push("task 不是对象");
    } else {
      if (form.task.placeholder !== undefined && typeof form.task.placeholder !== "string") {
        errors.push("task.placeholder 不是 string");
      }
      if (form.task.required !== undefined && typeof form.task.required !== "boolean") {
        errors.push("task.required 不是 boolean");
      }
    }
  }

  const fieldKeys = new Set();
  if (form.fields !== undefined) {
    if (!Array.isArray(form.fields)) {
      errors.push("fields 不是数组");
    } else {
      if (form.fields.length > 12) errors.push("fields 超过 12 项");
      form.fields.forEach((field, index) => {
        if (!isObject(field)) {
          errors.push(`fields[${index}] 不是对象`);
          return;
        }
        if (typeof field.key !== "string" || !KEY_PATTERN.test(field.key)) {
          errors.push(`fields[${index}].key 格式非法`);
        } else if (RESERVED_KEYS.has(field.key)) {
          errors.push(`fields[${index}].key 使用保留字`);
        } else if (fieldKeys.has(field.key)) {
          errors.push(`fields[${index}].key 重复`);
        } else {
          fieldKeys.add(field.key);
        }
        if (!FIELD_TYPES.has(field.type)) errors.push(`fields[${index}].type 非法`);
        if (field.type === "select") {
          if (!Array.isArray(field.options) || field.options.length === 0) {
            errors.push(`fields[${index}].options 不是非空数组`);
          } else {
            field.options.forEach((option, optionIndex) => {
              if (
                !isObject(option) ||
                typeof option.value !== "string" ||
                typeof option.label !== "string"
              ) {
                errors.push(`fields[${index}].options[${optionIndex}] 不是字符串对`);
              }
            });
          }
        }
      });
    }
  }

  if (typeof form.prompt_template !== "string" || form.prompt_template.trim() === "") {
    errors.push("prompt_template 不是非空 string");
  } else {
    const allowedVariables = new Set([...fieldKeys, ...RESERVED_KEYS]);
    for (const variable of form.prompt_template.matchAll(/{{\s*#?\s*([a-zA-Z0-9_]+)\s*}}/g)) {
      if (!allowedVariables.has(variable[1])) {
        errors.push(`prompt_template 引用未声明变量：${variable[1]}`);
      }
    }
  }
  return { found: true, errors };
}

function isObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function mark(value) {
  return value ? "✅" : "❌";
}

function escapeCell(value) {
  return String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
}

function renderHealth(results, generatedAt) {
  const reachable = results.filter((result) => result.repositoryReachable).length;
  const declared = results.filter((result) => result.declarationExists).length;
  const valid = results.filter((result) => result.declarationValid).length;
  const lines = [
    "# Registry 健康检查",
    "",
    `生成时间：${generatedAt}`,
    "",
    "## 汇总",
    "",
    "| 总数 | 可达 | 有声明 | 声明合法 |",
    "| ---: | ---: | ---: | ---: |",
    `| ${results.length} | ${reachable} | ${declared} | ${valid} |`,
    "",
    "## 明细",
    "",
    "| 条目 | 仓库可达 | 声明存在 | qsh-form 存在 | 声明合法 | 问题 |",
    "| --- | :---: | :---: | :---: | :---: | --- |",
  ];
  for (const result of results) {
    lines.push(
      `| ${escapeCell(result.name)} | ${mark(result.repositoryReachable)} | ${mark(result.declarationExists)} | ${mark(result.formFound)} | ${mark(result.declarationValid)} | ${escapeCell(result.problems.join("；") || "无")} |`,
    );
  }
  return `${lines.join("\n")}\n`;
}

await main();
