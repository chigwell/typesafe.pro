#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_NAME="${1:-typesafe-pro}"

projects_json="$(bash "${ROOT_DIR}/scripts/cf-env.sh" wrangler pages project list --json)"

if PROJECT_NAME="${PROJECT_NAME}" node -e '
  const fs = require("node:fs");
  const projectName = process.env.PROJECT_NAME;
  const projects = JSON.parse(fs.readFileSync(0, "utf8"));

  const exists = projects.some((project) => {
    return (
      project.name === projectName ||
      project.project_name === projectName ||
      project["Project Name"] === projectName
    );
  });

  process.exit(exists ? 0 : 1);
' <<<"${projects_json}"; then
  echo "Cloudflare Pages project '${PROJECT_NAME}' already exists."
  exit 0
fi

echo "Creating Cloudflare Pages project '${PROJECT_NAME}'."
bash "${ROOT_DIR}/scripts/cf-env.sh" wrangler pages project create "${PROJECT_NAME}" --production-branch=main
