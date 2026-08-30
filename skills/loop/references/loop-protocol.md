{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LoopState",
  "type": "object",
  "required": ["goal", "verifyCommand", "status", "iteration", "maxIterations", "history"],
  "properties": {
    "goal": { "type": "string" },
    "verifyCommand": { "type": "string" },
    "status": { "type": "string", "enum": ["RUNNING", "CONVERGED", "EXHAUSTED", "ABORTED"] },
    "iteration": { "type": "integer", "minimum": 0 },
    "maxIterations": { "type": "integer", "minimum": 1 },
    "intervalSeconds": { "type": "integer", "default": 30 },
    "history": {
      "type": "array",
      "items": {
        "type": "object",
        "required": ["iteration", "timestamp", "hypothesis", "exitCode", "verdict"],
        "properties": {
          "iteration": { "type": "integer" },
          "timestamp": { "type": "string" },
          "hypothesis": { "type": "string" },
          "exitCode": { "type": "integer" },
          "verdict": { "type": "string", "enum": ["PASS", "FAIL", "REVERTED"] },
          "notes": { "type": "string" }
        }
      }
    }
  }
}
