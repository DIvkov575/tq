use clap::{Parser, Subcommand};
use tq_core::{task_store_for, ProjectStore, Status, Task, UNASSIGNED};

/// tqctl - full-access CLI for the tq per-project task lanes.
///
/// Invoke as `tqctl-restricted` (or pass --restricted) to block `release`
/// (moving a task out of held) while keeping every other command.
#[derive(Parser)]
#[command(name = "tqctl")]
struct Cli {
    /// Block `release` (moving a task out of held), regardless of argv[0].
    #[arg(long, global = true)]
    restricted: bool,

    #[command(subcommand)]
    command: Command,
}

#[derive(Subcommand)]
enum Command {
    /// Push a new task onto a project's queue (default: _unassigned).
    Push {
        title: String,
        #[arg(long, default_value = "")]
        notes: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// List tasks in a project's lane.
    List {
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
        #[arg(long)]
        status: Option<String>,
        #[arg(long)]
        json: bool,
    },
    /// Mark a queued task running.
    Start {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Mark a running task completed.
    Complete {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Put a queued task on hold.
    Hold {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Release a held task back to queued. Blocked in restricted mode.
    Release {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Put a running task back on the queue.
    Requeue {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Edit a task's title/notes.
    Edit {
        id: String,
        #[arg(long)]
        title: Option<String>,
        #[arg(long)]
        notes: Option<String>,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Delete a task outright.
    Rm {
        id: String,
        #[arg(long, default_value = UNASSIGNED)]
        project: String,
    },
    /// Manage the project registry.
    Project {
        #[command(subcommand)]
        command: ProjectCommand,
    },
}

#[derive(Subcommand)]
enum ProjectCommand {
    /// Register a new project.
    Add { name: String, directory: String },
    /// List registered projects (plus the implicit _unassigned lane).
    List {
        #[arg(long)]
        json: bool,
    },
}

/// True if this process was invoked (via symlink) as `tqctl-restricted`.
fn invoked_as_restricted() -> bool {
    std::env::args()
        .next()
        .map(|a| {
            std::path::Path::new(&a)
                .file_name()
                .and_then(|n| n.to_str())
                .map(|n| n.contains("restricted"))
                .unwrap_or(false)
        })
        .unwrap_or(false)
}

fn print_task(t: &Task) {
    println!("[{}] ({}) {}", t.id, t.status.as_str(), t.title);
    if !t.notes.is_empty() {
        println!("       {}", t.notes);
    }
}

fn main() {
    let cli = Cli::parse();
    let restricted = cli.restricted || invoked_as_restricted();

    if let Err(e) = run(cli.command, restricted) {
        eprintln!("error: {e}");
        std::process::exit(1);
    }
}

fn run(command: Command, restricted: bool) -> tq_core::Result<()> {
    match command {
        Command::Push {
            title,
            notes,
            project,
        } => {
            let store = task_store_for(&project)?;
            let task = store.push(&title, &notes)?;
            print_task(&task);
        }
        Command::List {
            project,
            status,
            json,
        } => {
            let store = task_store_for(&project)?;
            let mut tasks = store.list()?;
            if let Some(status) = status {
                let status: Status = status
                    .parse()
                    .map_err(|_| tq_core::Error::TaskNotFound(format!("bad status {status}")))?;
                tasks.retain(|t| t.status == status);
            }
            if json {
                println!("{}", serde_json::to_string_pretty(&tasks).unwrap());
            } else if tasks.is_empty() {
                println!("(empty)");
            } else {
                for t in &tasks {
                    print_task(t);
                }
            }
        }
        Command::Start { id, project } => {
            let store = task_store_for(&project)?;
            print_task(&store.start(&id)?);
        }
        Command::Complete { id, project } => {
            let store = task_store_for(&project)?;
            print_task(&store.complete(&id)?);
        }
        Command::Hold { id, project } => {
            let store = task_store_for(&project)?;
            print_task(&store.hold(&id)?);
        }
        Command::Release { id, project } => {
            if restricted {
                return Err(tq_core::Error::Restricted(
                    "release (moving a task out of held)".to_string(),
                ));
            }
            let store = task_store_for(&project)?;
            print_task(&store.release(&id)?);
        }
        Command::Requeue { id, project } => {
            let store = task_store_for(&project)?;
            print_task(&store.requeue(&id)?);
        }
        Command::Edit {
            id,
            title,
            notes,
            project,
        } => {
            let store = task_store_for(&project)?;
            print_task(&store.edit(&id, title.as_deref(), notes.as_deref())?);
        }
        Command::Rm { id, project } => {
            let store = task_store_for(&project)?;
            store.remove(&id)?;
            println!("removed {id}");
        }
        Command::Project { command } => match command {
            ProjectCommand::Add { name, directory } => {
                let store = ProjectStore::new();
                let project = store.add(&name, &directory)?;
                println!("[{}] dir={}", project.name, project.directory);
            }
            ProjectCommand::List { json } => {
                let store = ProjectStore::new();
                let projects = store.list()?;
                if json {
                    println!("{}", serde_json::to_string_pretty(&projects).unwrap());
                } else if projects.is_empty() {
                    println!("(no registered projects; {UNASSIGNED} lane is always available)");
                } else {
                    for p in &projects {
                        println!("[{}] dir={}", p.name, p.directory);
                    }
                }
            }
        },
    }
    Ok(())
}
