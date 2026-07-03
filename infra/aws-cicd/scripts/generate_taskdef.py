"""
AgentAtlas — Generate CodeDeploy task definition
Called by buildspec_build.yml during the build stage.

Reads the current ECS task definition from stdin (JSON),
strips the ECS-managed read-only fields that cause re-registration to fail,
injects the IMAGE_NAME placeholder that CodeDeploy replaces with the real URI,
and writes the result to taskdef.json.

Usage (from buildspec):
  aws ecs describe-task-definition \
    --task-definition agentatlas-backend \
    --query taskDefinition --output json | python3 scripts/generate_taskdef.py
"""
import json
import sys

td = json.load(sys.stdin)

for field in [
    "taskDefinitionArn", "revision", "status",
    "requiresAttributes", "compatibilities",
    "registeredAt", "registeredBy",
]:
    td.pop(field, None)

# CodeDeploy replaces the string <IMAGE_NAME> with the actual ECR URI
# from the build artifact metadata before creating the new task set.
td["containerDefinitions"][0]["image"] = "<IMAGE_NAME>"

with open("taskdef.json", "w") as f:
    json.dump(td, f, indent=2)

print("taskdef.json written")
json.load(open("taskdef.json"))  # verify it round-trips cleanly
print("taskdef.json validated")
