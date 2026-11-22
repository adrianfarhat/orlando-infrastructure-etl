// Which Python runs the design tooling (T-97 decisions Q9 and P2-A).
// Only the machine-level value of featureDesigner.pythonPath counts (it is stored in the
// user's settings, never in a workspace): a repository cannot choose the program that runs.
// When it is empty, the repository's .venv interpreter is *suggested* and saved only after
// the user confirms.
"use strict";
const path = require("path");

const SETTING = "pythonPath";

/** The configured interpreter from a configuration.inspect() result, and the scopes that were ignored. */
function configured(inspected) {
  const ignored = [];
  for (const key of ["workspaceValue", "workspaceFolderValue", "workspaceLanguageValue", "workspaceFolderLanguageValue"])
    if (inspected && typeof inspected[key] === "string" && inspected[key].trim()) ignored.push(key);
  const value = inspected && typeof inspected.globalValue === "string" ? inspected.globalValue.trim() : "";
  return { path: value, ignored };
}

/** The repository's virtual-environment interpreter, if it exists. */
function candidate(root, exists) {
  const options = process.platform === "win32"
    ? [path.join(root, ".venv", "Scripts", "python.exe")]
    : [path.join(root, ".venv", "bin", "python3"), path.join(root, ".venv", "bin", "python")];
  return options.find((p) => exists(p)) || "";
}

/**
 * Resolve the interpreter with the VS Code API (`vscode` passed in for testability).
 * Returns the path, or throws when the user declines.
 */
async function ensurePython(vscode, root, log, fsExists) {
  const cfg = vscode.workspace.getConfiguration("featureDesigner");
  const { path: chosen, ignored } = configured(cfg.inspect(SETTING));
  if (ignored.length) {
    log(`[python] ignored featureDesigner.${SETTING} from ${ignored.join(", ")} (machine-level setting only)`);
    if (!ensurePython.warned) {
      ensurePython.warned = true;
      vscode.window.showWarningMessage("Feature Designer ignores featureDesigner.pythonPath in workspace or folder settings: a repository cannot choose the interpreter. Use your user (machine) settings instead.");
    }
  }
  if (chosen) return chosen;
  const suggestion = candidate(root, fsExists);
  const use = "Use and Save", choose = "Choose Another…";
  const answer = await vscode.window.showInformationMessage(
    suggestion
      ? `Feature Designer runs the design tooling with Python. Use this interpreter?\n\n${suggestion}\n\nIt will be saved to your machine-level settings (featureDesigner.pythonPath).`
      : "Feature Designer runs the design tooling with Python, and no interpreter is configured. Choose one (it will be saved to your machine-level settings).",
    { modal: true }, ...(suggestion ? [use, choose] : [choose]));
  let picked = "";
  if (answer === use) picked = suggestion;
  else if (answer === choose) picked = await pickInterpreter(vscode);
  if (!picked) throw new Error("no Python interpreter configured (Feature Designer: Select Python Interpreter)");
  await cfg.update(SETTING, picked, vscode.ConfigurationTarget.Global);
  log(`[python] saved featureDesigner.${SETTING} = ${picked} (user/machine settings)`);
  return picked;
}

async function pickInterpreter(vscode) {
  const uris = await vscode.window.showOpenDialog({
    canSelectMany: false, openLabel: "Use This Interpreter", title: "Python interpreter for Feature Designer",
    filters: process.platform === "win32" ? { Python: ["exe"] } : undefined,
  });
  return uris && uris[0] ? uris[0].fsPath : "";
}

module.exports = { configured, candidate, ensurePython, pickInterpreter, SETTING };
