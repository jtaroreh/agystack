#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

function globToRegex(glob) {
	let p = glob.replace(/^\.\//, "");

	// Tokenize glob special sequences before regex character escaping
	p = p
		.replace(/\*\*\//g, "__GLOB_GLOBSTAR_SLASH__")
		.replace(/\/\*\*/g, "__GLOB_SLASH_GLOBSTAR__")
		.replace(/\*\*/g, "__GLOB_GLOBSTAR__")
		.replace(/\*/g, "__GLOB_STAR__")
		.replace(/\?/g, "__GLOB_QUESTION__");

	// Escape regex special characters
	p = p.replace(/[.+^${}()|[\]\\]/g, "\\$&");

	// Substitute tokens with regex expressions
	p = p
		.replace(/__GLOB_GLOBSTAR_SLASH__/g, "(?:^|.*/)")
		.replace(/__GLOB_SLASH_GLOBSTAR__/g, "(?:/.*)?")
		.replace(/__GLOB_GLOBSTAR__/g, ".*")
		.replace(/__GLOB_STAR__/g, "[^/]*")
		.replace(/__GLOB_QUESTION__/g, "[^/]");

	return new RegExp(`^${p}$`);
}

function matchRule(filePath, pattern) {
	const normalized = filePath.replace(/^\.\//, "");
	const rx = globToRegex(pattern);
	return rx.test(normalized) || rx.test(path.basename(normalized));
}

const manifestPath = process.argv[2] || path.resolve("rules/rule-manifest.json");
const filesToCheck = process.argv.slice(3);

if (!fs.existsSync(manifestPath)) {
	console.error(`error: manifest not found at ${manifestPath}`);
	process.exit(1);
}

const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
const matchedRules = new Map();

for (const filePath of filesToCheck) {
	for (const rule of manifest.rules || []) {
		for (const pattern of rule.patterns) {
			if (matchRule(filePath, pattern)) {
				matchedRules.set(rule.id, rule);
				break;
			}
		}
	}
}

const output = {
	matchedRuleIds: Array.from(matchedRules.keys()),
	rules: Array.from(matchedRules.values()),
};

console.log(JSON.stringify(output, null, 2));
