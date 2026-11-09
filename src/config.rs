use crate::{Error, Result};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeMap,
    path::{Path, PathBuf},
};

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Config {
    pub namespace: String,
    pub secrets: BTreeMap<String, SecretDefinition>,
    pub operations: BTreeMap<String, Operation>,
    #[serde(default)]
    pub allow_http_loopback: bool,
}

#[derive(Clone, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SecretDefinition {
    pub description: String,
    #[serde(default)]
    pub environment: Option<String>,
}

#[derive(Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Operation {
    Capture {
        secret: String,
        source: Source,
        #[serde(default)]
        replace: bool,
    },
    Generate {
        secret: String,
        bytes: usize,
        #[serde(default)]
        replace: bool,
    },
    Deliver {
        secret: String,
        destination: Destination,
    },
}
impl Operation {
    pub fn secret(&self) -> &str {
        match self {
            Self::Capture { secret, .. }
            | Self::Generate { secret, .. }
            | Self::Deliver { secret, .. } => secret,
        }
    }
}

#[derive(Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Source {
    File {
        path: PathBuf,
        #[serde(default)]
        json_pointer: Option<String>,
    },
    Environment {
        variable: String,
    },
    Command {
        command: CommandSpec,
        #[serde(default)]
        json_pointer: Option<String>,
    },
    Http {
        request: HttpRequest,
        json_pointer: String,
    },
    Browser {
        page: BrowserPage,
        selector: String,
        #[serde(default)]
        click: Option<String>,
    },
}

#[derive(Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Destination {
    File {
        path: PathBuf,
        #[serde(default)]
        replace: bool,
    },
    Command {
        command: CommandSpec,
        variable: String,
    },
    Http {
        request: HttpRequest,
        placement: Placement,
    },
    Browser {
        page: BrowserPage,
        selector: String,
        #[serde(default)]
        submit: Option<String>,
        #[serde(default)]
        success_selector: Option<String>,
    },
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CommandSpec {
    pub program: PathBuf,
    #[serde(default)]
    pub args: Vec<String>,
    pub cwd: PathBuf,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
    /// Names of existing secrets to bind to child environment variables.
    #[serde(default)]
    pub secret_env: BTreeMap<String, String>,
}
pub fn default_timeout() -> u64 {
    15
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HttpRequest {
    pub url: String,
    #[serde(default = "get_method")]
    pub method: String,
    #[serde(default)]
    pub json: Option<serde_json::Value>,
    #[serde(default)]
    pub auth: Option<HttpAuth>,
}
fn get_method() -> String {
    "GET".into()
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct HttpAuth {
    pub secret: String,
    pub header: String,
    #[serde(default)]
    pub prefix: String,
}

#[derive(Clone, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Placement {
    Header {
        name: String,
        #[serde(default)]
        prefix: String,
    },
    JsonField {
        field: String,
    },
}

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserPage {
    /// Dedicated local Chrome CDP endpoint. Never connect to a remote browser.
    pub endpoint: String,
    /// Exact URL of an already-open page; ASM never lists pages to the agent.
    pub url: String,
    #[serde(default = "default_timeout")]
    pub timeout_seconds: u64,
}

pub fn valid_name(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 128
        && s.bytes()
            .all(|c| c.is_ascii_alphanumeric() || b"_-/".contains(&c))
}
impl Config {
    pub fn load(path: &Path) -> Result<Self> {
        let file = crate::open_regular(path)?;
        let bytes = crate::engine::bounded_read(file)?;
        let config: Self = serde_json::from_slice(&bytes).map_err(|_| Error("invalid_config"))?;
        config.validate()?;
        Ok(config)
    }
    pub fn validate(&self) -> Result<()> {
        if !valid_name(&self.namespace) || self.secrets.is_empty() {
            return Err(Error("invalid_config"));
        }
        for (name, definition) in &self.secrets {
            if !valid_name(name) || definition.description.len() > 1024 {
                return Err(Error("invalid_config"));
            }
            if definition
                .environment
                .as_deref()
                .is_some_and(|s| !valid_name(s))
            {
                return Err(Error("invalid_secret_environment"));
            }
        }
        for (name, op) in &self.operations {
            if !valid_name(name) || !self.secrets.contains_key(op.secret()) {
                return Err(Error("invalid_config"));
            }
            if let Operation::Generate { bytes, .. } = op
                && !(16..=1024).contains(bytes)
            {
                return Err(Error("invalid_generation_size"));
            }
            match op {
                Operation::Capture { source, .. } => match source {
                    Source::Command { command, .. } => self.validate_command(command)?,
                    Source::Http { request, .. } => self.validate_http(request)?,
                    Source::Browser { page, selector, .. } => {
                        self.validate_browser(page, selector)?
                    }
                    Source::Environment { variable } if !valid_variable(variable) => {
                        return Err(Error("invalid_environment_name"));
                    }
                    _ => (),
                },
                Operation::Deliver { destination, .. } => match destination {
                    Destination::Command { command, variable } => {
                        self.validate_command(command)?;
                        if !valid_variable(variable) || command.secret_env.contains_key(variable) {
                            return Err(Error("invalid_environment_binding"));
                        }
                    }
                    Destination::Http { request, .. } => self.validate_http(request)?,
                    Destination::Browser { page, selector, .. } => {
                        self.validate_browser(page, selector)?
                    }
                    _ => (),
                },
                _ => (),
            }
        }
        Ok(())
    }
    fn validate_command(&self, command: &CommandSpec) -> Result<()> {
        if !command.program.is_absolute()
            || !command.cwd.is_absolute()
            || !(1..=60).contains(&command.timeout_seconds)
        {
            return Err(Error("invalid_command_config"));
        }
        for (variable, secret) in &command.secret_env {
            if !valid_variable(variable) || !self.secrets.contains_key(secret) {
                return Err(Error("invalid_environment_binding"));
            }
        }
        Ok(())
    }
    fn validate_http(&self, request: &HttpRequest) -> Result<()> {
        crate::engine::validate_url(&request.url, self.allow_http_loopback)?;
        reqwest::Method::from_bytes(request.method.as_bytes())
            .map_err(|_| Error("invalid_http_method"))?;
        if let Some(auth) = &request.auth
            && !self.secrets.contains_key(&auth.secret)
        {
            return Err(Error("unknown_secret"));
        }
        Ok(())
    }
    fn validate_browser(&self, page: &BrowserPage, selector: &str) -> Result<()> {
        crate::engine::validate_url(&page.url, self.allow_http_loopback)?;
        let url = url::Url::parse(&page.endpoint).map_err(|_| Error("invalid_browser_endpoint"))?;
        if url.scheme() != "http"
            || !crate::engine::loopback(&url)
            || !url.username().is_empty()
            || url.password().is_some()
            || selector.is_empty()
            || !(1..=60).contains(&page.timeout_seconds)
        {
            return Err(Error("invalid_browser_config"));
        }
        Ok(())
    }
}

fn valid_variable(s: &str) -> bool {
    !s.is_empty()
        && !s.as_bytes()[0].is_ascii_digit()
        && s.bytes().all(|b| b.is_ascii_alphanumeric() || b == b'_')
}
