#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";

function globToRegex(glob) {
	const escaped = glob
		.replace(/[.+^${}()|[\]\\]/g, "\\$&")
		.replace(/\*\*/g, ".*")
		.replace(/(?<!\.)\*/g, "[^/]*");
	return new RegExp(`^${escaped}$`);
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
