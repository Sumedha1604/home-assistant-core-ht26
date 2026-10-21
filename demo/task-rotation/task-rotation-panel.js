const TODO_ENTITY_ID = "todo.household_task";
const META_START = "[task-rotation:v1]";
const META_END = "[/task-rotation]";

function parseParticipants(text) {
  const names = text
    .split(",")
    .map((name) => name.trim())
    .filter(Boolean);

  const unique = [...new Set(names.map((name) => name.toLowerCase()))];

  if (
    names.length === 0 ||
    names.length > 12 ||
    unique.length !== names.length ||
    names.some((name) => name.length > 60)
  ) {
    throw new Error(
      "Enter 1 to 12 different names, separated by commas (up to 60 characters each).",
    );
  }

  return names;
}

function readRotation(description) {
  const text = typeof description === "string" ? description : "";

  const start = text.indexOf(META_START);
  const end =
    start < 0 ? -1 : text.indexOf(META_END, start + META_START.length);

  if (start < 0 || end < 0) {
    return {
      rotation: null,
      notes: text.trim(),
    };
  }

  try {
    const raw = JSON.parse(text.slice(start + META_START.length, end));

    if (
      !Array.isArray(raw.people) ||
      !raw.people.length ||
      !raw.people.every((name) => typeof name === "string" && name.trim()) ||
      !Number.isInteger(raw.index) ||
      !Number.isInteger(raw.completed)
    ) {
      throw new Error("Invalid rotation data");
    }

    return {
      rotation: {
        people: raw.people,
        index:
          ((raw.index % raw.people.length) + raw.people.length) %
          raw.people.length,
        completed: Math.max(0, raw.completed),
      },
      notes: (text.slice(0, start) + text.slice(end + META_END.length)).trim(),
    };
  } catch (_error) {
    return {
      rotation: null,
      notes: text.trim(),
      invalid: true,
    };
  }
}

function writeRotation(rotation, notes = "") {
  return [notes.trim(), `${META_START}${JSON.stringify(rotation)}${META_END}`]
    .filter(Boolean)
    .join("\n\n");
}

function el(tag, className = "", text) {
  const node = document.createElement(tag);

  if (className) {
    node.className = className;
  }

  if (text !== undefined) {
    node.textContent = text;
  }

  return node;
}

class TaskRotationPanel extends HTMLElement {
  constructor() {
    super();

    this._hass = null;
    this._loaded = false;
    this._busy = false;
    this._items = [];
  }

  set hass(hass) {
    this._hass = hass;

    if (this.isConnected && !this._loaded) {
      this._loaded = true;
      void this.loadTasks();
    }
  }

  connectedCallback() {
    if (!this.shadowRoot) {
      const root = this.attachShadow({
        mode: "open",
      });

      root.innerHTML = `
        <style>
          :host {
            display: block;
            color: var(--primary-text-color);
          }

          .container {
            max-width: 900px;
            margin: 0 auto;
            padding: 24px;
          }

          header,
          .actions,
          .form-actions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            align-items: center;
          }

          header {
            justify-content: space-between;
          }

          .card {
            margin: 16px 0;
            padding: 20px;
            background: var(--card-background-color);
            border: 1px solid var(--divider-color);
            border-radius: 12px;
          }

          button {
            padding: 10px 14px;
            border: 0;
            border-radius: 8px;
            cursor: pointer;
            background: var(--primary-color);
            color: white;
            font: inherit;
          }

          button.secondary {
            background: var(--secondary-background-color);
            color: var(--primary-text-color);
          }

          button:disabled {
            opacity: 0.55;
            cursor: wait;
          }

          label {
            display: block;
            margin: 14px 0 6px;
            font-weight: 600;
          }

          input {
            box-sizing: border-box;
            display: block;
            width: 100%;
            padding: 11px;
            color: var(--primary-text-color);
            background: var(--secondary-background-color);
            border: 1px solid var(--divider-color);
            border-radius: 8px;
            font: inherit;
          }

          .form-actions {
            margin-top: 16px;
          }

          .muted {
            color: var(--secondary-text-color);
          }

          .error {
            color: var(--error-color);
          }

          .person {
            font-size: 1.1rem;
            font-weight: 650;
          }

          .progress {
            height: 8px;
            background: var(--divider-color);
            border-radius: 999px;
            overflow: hidden;
          }

          .progress > span {
            height: 100%;
            display: block;
            background: var(--primary-color);
          }

          .inline-form {
            margin-top: 14px;
            padding-top: 10px;
            border-top: 1px solid var(--divider-color);
          }

          [hidden] {
            display: none !important;
          }

          @media (max-width: 600px) {
            .container {
              padding: 16px;
            }
          }
        </style>

        <div class="container">
          <header>
            <h1>Task Rotation</h1>

            <div class="actions">
              <button id="new-task" type="button">
                Create Task
              </button>

              <button
                id="refresh"
                type="button"
                class="secondary"
              >
                Refresh Tasks
              </button>
            </div>
          </header>

          <form id="create-form" class="card" hidden>
            <h2>Create a rotating task</h2>

            <label for="task-name">
              Task name
            </label>

            <input
              id="task-name"
              required
              maxlength="255"
              placeholder="Clean the kitchen"
            />

            <label for="task-people">
              Participants (comma-separated)
            </label>

            <input
              id="task-people"
              required
              placeholder="Person A, Person B, Person C"
            />

            <label for="task-due">
              Due date (optional)
            </label>

            <input id="task-due" type="date" />

            <p class="muted">
              The first participant gets the first turn.
            </p>

            <p id="form-message" role="status"></p>

            <div class="form-actions">
              <button id="save-task" type="submit">
                Save Task
              </button>

              <button
                id="cancel-task"
                type="button"
                class="secondary"
              >
                Cancel
              </button>
            </div>
          </form>

          <p
            id="notice"
            role="status"
            aria-live="polite"
          ></p>

          <p
            id="status"
            class="muted"
            role="status"
          >
            Loading tasks...
          </p>

          <div id="tasks"></div>
        </div>
      `;

      root.getElementById("new-task").addEventListener("click", () => {
        root.getElementById("create-form").hidden = false;

        root.getElementById("form-message").textContent = "";

        root.getElementById("task-name").focus();
      });

      root.getElementById("cancel-task").addEventListener("click", () => {
        root.getElementById("create-form").hidden = true;

        root.getElementById("create-form").reset();
      });

      root
        .getElementById("refresh")
        .addEventListener("click", () => void this.loadTasks());

      root
        .getElementById("create-form")
        .addEventListener("submit", (event) => void this.createTask(event));
    }

    if (this._hass && !this._loaded) {
      this._loaded = true;
      void this.loadTasks();
    }
  }

  _notice(message, error = false) {
    const node = this.shadowRoot.getElementById("notice");

    node.textContent = message;
    node.className = error ? "error" : "muted";
  }

  async createTask(event) {
    event.preventDefault();

    if (!this._hass || this._busy) {
      return;
    }

    const root = this.shadowRoot;

    const name = root.getElementById("task-name").value.trim();

    const dueDate = root.getElementById("task-due").value;

    const message = root.getElementById("form-message");

    let people;

    try {
      people = parseParticipants(root.getElementById("task-people").value);

      if (!name) {
        throw new Error("Please enter a task name.");
      }
    } catch (error) {
      message.className = "error";
      message.textContent = error.message;
      return;
    }

    const data = {
      item: name,
      description: writeRotation({
        people,
        index: 0,
        completed: 0,
      }),
    };

    if (dueDate) {
      data.due_date = dueDate;
    }

    this._busy = true;

    root.getElementById("save-task").disabled = true;

    message.textContent = "Saving task...";
    message.className = "muted";

    try {
      await this._hass.callService("todo", "add_item", data, {
        entity_id: TODO_ENTITY_ID,
      });

      root.getElementById("create-form").reset();

      root.getElementById("create-form").hidden = true;

      await this.loadTasks();

      this._notice(`Created task: ${name}`);
    } catch (error) {
      console.error("Unable to create task", error);

      message.className = "error";

      message.textContent = `Unable to create task: ${
        error.message || "Check Console"
      }`;
    } finally {
      this._busy = false;

      root.getElementById("save-task").disabled = false;
    }
  }

  async loadTasks() {
    if (!this._hass || !this.shadowRoot) {
      return;
    }

    const root = this.shadowRoot;

    root.getElementById("status").textContent = "Loading tasks...";

    try {
      const response = await this._hass.callService(
        "todo",
        "get_items",
        { status: "needs_action" },
        { entity_id: TODO_ENTITY_ID },
        false,
        true,
      );

      const items = response?.response?.[TODO_ENTITY_ID]?.items;

      if (!Array.isArray(items)) {
        throw new Error("Unexpected response from To-do list");
      }

      this._items = items;

      this.renderTasks();

      root.getElementById("status").textContent =
        `${items.length} active task(s)`;
    } catch (error) {
      console.error("Unable to load tasks", error);

      root.getElementById("status").textContent = "Unable to load tasks.";
    }
  }

  renderTasks() {
    const container = this.shadowRoot.getElementById("tasks");

    container.replaceChildren();

    if (!this._items.length) {
      container.appendChild(
        el("p", "muted", "No active tasks. Select Create Task to add one."),
      );
      return;
    }

    for (const task of this._items) {
      const { rotation, notes, invalid } = readRotation(task.description);

      const card = el("article", "card");

      card.appendChild(el("h3", "", task.summary || "Unnamed task"));

      card.appendChild(
        el("p", "muted", task.due ? `Due: ${task.due}` : "No due date"),
      );

      if (notes && !invalid) {
        card.appendChild(el("p", "muted", notes));
      }

      if (invalid) {
        card.appendChild(
          el(
            "p",
            "error",
            "This task has invalid rotation metadata. Edit its description before assigning participants.",
          ),
        );

        container.appendChild(card);
        continue;
      }

      if (rotation) {
        card.appendChild(
          el(
            "p",
            "person",
            `Current assignee: ${rotation.people[rotation.index]}`,
          ),
        );

        card.appendChild(
          el("p", "muted", `People: ${rotation.people.join(" → ")}`),
        );

        card.appendChild(
          el(
            "p",
            "muted",
            `Turns completed: ${rotation.completed} | Position: ${
              rotation.index + 1
            } of ${rotation.people.length}`,
          ),
        );

        const progress = el("div", "progress");

        const fill = el("span");

        fill.style.width = `${
          ((rotation.index + 1) / rotation.people.length) * 100
        }%`;

        progress.appendChild(fill);
        card.appendChild(progress);

        const next = el("button", "", "Mark turn completed & rotate");

        next.type = "button";
        next.style.marginTop = "16px";

        next.addEventListener("click", () => void this.advanceTask(task));

        card.appendChild(next);
      } else {
        card.appendChild(el("p", "muted", "No participants assigned yet."));
      }

      const edit = el(
        "button",
        "secondary",
        rotation ? "Edit participants" : "Assign participants",
      );

      edit.type = "button";

      edit.style.marginLeft = rotation ? "8px" : "0";

      edit.style.marginTop = "16px";

      card.appendChild(edit);

      const form = el("form", "inline-form");

      form.hidden = true;

      const label = el("label", "", "Participants (comma-separated)");

      const input = el("input");

      input.required = true;

      input.placeholder = "Person A, Person B, Person C";

      input.value = rotation ? rotation.people.join(", ") : "";

      const save = el("button", "", "Save participants");

      save.type = "submit";

      const cancel = el("button", "secondary", "Cancel");

      cancel.type = "button";
      cancel.style.marginLeft = "8px";

      form.append(label, input, save, cancel);

      card.appendChild(form);

      edit.addEventListener("click", () => {
        form.hidden = false;
        input.focus();
      });

      cancel.addEventListener("click", () => {
        form.hidden = true;
      });

      form.addEventListener("submit", (event) => {
        event.preventDefault();

        void this.saveParticipants(task, input.value);
      });

      container.appendChild(card);
    }
  }

  async saveParticipants(task, input) {
    if (this._busy) {
      return;
    }

    let people;

    try {
      people = parseParticipants(input);
    } catch (error) {
      this._notice(error.message, true);
      return;
    }

    const { rotation, notes, invalid } = readRotation(task.description);

    if (invalid) {
      return this._notice("Cannot update malformed rotation metadata.", true);
    }

    const currentName = rotation?.people[rotation.index];

    const retainedIndex = people.findIndex((person) => person === currentName);

    const next = {
      people,
      index: retainedIndex >= 0 ? retainedIndex : 0,
      completed: rotation?.completed ?? 0,
    };

    await this.updateRotation(task, next, notes, "Participants saved.");
  }

  async advanceTask(task) {
    if (this._busy) {
      return;
    }

    const { rotation, notes, invalid } = readRotation(task.description);

    if (invalid || !rotation) {
      return this._notice("No valid participants for this task.", true);
    }

    const next = {
      ...rotation,
      index: (rotation.index + 1) % rotation.people.length,
      completed: rotation.completed + 1,
    };

    await this.updateRotation(
      task,
      next,
      notes,
      `Turn completed. Next: ${next.people[next.index]}`,
    );
  }

  async updateRotation(task, rotation, notes, successMessage) {
    if (this._busy) {
      return;
    }

    this._busy = true;

    this._notice("Saving rotation...");

    try {
      await this._hass.callService(
        "todo",
        "update_item",
        {
          item: task.uid || task.summary,
          description: writeRotation(rotation, notes),
        },
        {
          entity_id: TODO_ENTITY_ID,
        },
      );

      await this.loadTasks();

      this._notice(successMessage);
    } catch (error) {
      console.error("Unable to save rotation", error);

      this._notice(
        `Unable to save rotation: ${error.message || "Check Console"}`,
        true,
      );
    } finally {
      this._busy = false;
    }
  }
}

customElements.define("task-rotation-panel", TaskRotationPanel);
