"use strict";
// Shared test helpers: where the repository and its Python are.
const fs = require("fs");
const path = require("path");

const EXT = path.resolve(__dirname, "..", "..");
const REPO = path.resolve(EXT, "..", "..");

/** The interpreter for tests that run the real design tooling (FEATURE_DESIGNER_TEST_PYTHON or the repo's .venv). */
function testPython() {
  const candidates = [process.env.FEATURE_DESIGNER_TEST_PYTHON, path.join(REPO, ".venv", "Scripts", "python.exe"),
                      path.join(REPO, ".venv", "bin", "python")].filter(Boolean);
  return candidates.find((p) => fs.existsSync(p)) || null;
}

module.exports = { EXT, REPO, testPython };
