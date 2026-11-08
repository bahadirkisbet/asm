use crate::engine::Engine;
use rmcp::{
    handler::server::wrapper::Parameters,
    model::{CallToolResult, ContentBlock},
    tool, tool_router,
};
use serde::Deserialize;
use std::sync::{Arc, Mutex};

#[derive(Clone)]
pub struct Server {
    engine: Arc<Mutex<Engine>>,
}
#[derive(Deserialize, schemars::JsonSchema)]
#[serde(deny_unknown_fields)]
pub struct Execute {
    /// Exact operation name from asm_catalog. Never a secret value.
    operation: String,
}

impl Server {
    pub fn new(engine: Engine) -> Self {
        Self {
            engine: Arc::new(Mutex::new(engine)),
        }
    }
}

#[tool_router(server_handler)]
impl Server {
    #[tool(
        description = "List configured secret references, descriptions and operation names. Never returns secret values."
    )]
    async fn asm_catalog(&self) -> CallToolResult {
        match self.engine.lock() {
            Ok(engine) => {
                CallToolResult::success(vec![ContentBlock::text(engine.catalog().to_string())])
            }
            Err(_) => failure("internal_state_failed"),
        }
    }

    #[tool(
        description = "Execute an authorized named local operation: capture, generate or deliver a secret. Only status and a secret reference are returned. Do not pass plaintext secrets. Side effects are defined in the trusted local config; consult that config before choosing an operation. A failure after an external side effect may require checking the provider before retrying."
    )]
    async fn asm_execute(&self, Parameters(args): Parameters<Execute>) -> CallToolResult {
        let engine = self.engine.clone();
        match tokio::task::spawn_blocking(move || {
            let mut engine = engine
                .lock()
                .map_err(|_| crate::Error("internal_state_failed"))?;
            engine.execute(&args.operation)
        })
        .await
        {
            Ok(Ok(outcome)) => match serde_json::to_string(&outcome) {
                Ok(text) => CallToolResult::success(vec![ContentBlock::text(text)]),
                Err(_) => failure("result_encoding_failed"),
            },
            Ok(Err(error)) => failure(error.0),
            Err(_) => failure("operation_worker_failed"),
        }
    }
}

fn failure(code: &'static str) -> CallToolResult {
    CallToolResult::error(vec![ContentBlock::text(
        serde_json::json!({"error":code}).to_string(),
    )])
}
