use agentic_secret_manager::{
    Error, Result,
    config::Config,
    engine::Engine,
    mcp::Server,
    store::{MemoryStore, OsStore, Store},
};
use clap::{Parser, Subcommand};
use rmcp::ServiceExt;
use std::path::PathBuf;

#[derive(Parser)]
#[command(
    name = "asm",
    version,
    about = "Agentic Secret Manager — references in, safe status out"
)]
struct Cli {
    /// Trusted configuration containing operation definitions, never secret values.
    #[arg(long, default_value = ".asm.json", global = true)]
    config: PathBuf,
    /// In-memory test store, discarded at exit. Never falls back from OS storage.
    #[arg(long, global = true)]
    ephemeral: bool,
    #[command(subcommand)]
    command: Commands,
}
#[derive(Subcommand)]
enum Commands {
    /// Print reference metadata and available named operations.
    Catalog,
    /// Execute one configured operation; no raw output is ever printed.
    Execute { operation: String },
    /// Remove one configured secret from storage (human CLI only).
    Delete { secret: String },
    /// Serve MCP over stdio for Claude Code, Codex, and other MCP clients.
    Mcp,
    /// Validate configuration syntax and declared secret references.
    Check,
}

fn main() {
    // Panic payloads from libraries can contain raw upstream data.
    std::panic::set_hook(Box::new(|_| eprintln!("{{\"error\":\"internal_panic\"}}")));
    if let Err(error) = run(Cli::parse()) {
        eprintln!("{}", serde_json::json!({"error":error.0}));
        std::process::exit(1);
    }
}
fn run(cli: Cli) -> Result<()> {
    let config_path = cli
        .config
        .canonicalize()
        .map_err(|_| Error("config_read_failed"))?;
    let config = Config::load(&config_path)?;
    if matches!(cli.command, Commands::Check) {
        println!("{{\"status\":\"config_valid\"}}");
        return Ok(());
    }
    let store: Box<dyn Store> = if cli.ephemeral {
        Box::new(MemoryStore::default())
    } else {
        Box::new(OsStore::new(&config.namespace))
    };
    let mut engine = Engine::new(
        config,
        store,
        config_path
            .parent()
            .ok_or(Error("config_read_failed"))?
            .into(),
        !cli.ephemeral,
    )?;
    match cli.command {
        Commands::Catalog => println!("{}", engine.catalog()),
        Commands::Execute { operation } => println!(
            "{}",
            serde_json::to_string(&engine.execute(&operation)?)
                .map_err(|_| Error("result_encoding_failed"))?
        ),
        Commands::Delete { secret } => {
            engine.delete(&secret)?;
            println!("{{\"status\":\"deleted\"}}");
        }
        Commands::Mcp => {
            tokio::runtime::Runtime::new()
                .map_err(|_| Error("runtime_start_failed"))?
                .block_on(async move {
                    let service = Server::new(engine)
                        .serve(rmcp::transport::stdio())
                        .await
                        .map_err(|_| Error("mcp_start_failed"))?;
                    service
                        .waiting()
                        .await
                        .map_err(|_| Error("mcp_transport_failed"))?;
                    Ok(())
                })?;
        }
        Commands::Check => unreachable!(),
    }
    Ok(())
}
