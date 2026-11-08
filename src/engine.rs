use crate::{
    Error, MAX_CAPTURE, Result,
    browser::Browser,
    config::*,
    process,
    store::{self, Store},
};
use base64::Engine as _;
use serde::Serialize;
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    io::{Read, Write},
    path::{Path, PathBuf},
    time::Duration,
};
use zeroize::Zeroizing;

pub struct Engine {
    pub config: Config,
    store: Box<dyn Store>,
    base: PathBuf,
    persistent: bool,
}

#[derive(Serialize)]
pub struct Outcome {
    pub operation: String,
    pub secret_ref: String,
    pub status: &'static str,
}

impl Engine {
    pub fn new(
        config: Config,
        store: Box<dyn Store>,
        base: PathBuf,
        persistent: bool,
    ) -> Result<Self> {
        config.validate()?;
        Ok(Self {
            config,
            store,
            base,
            persistent,
        })
    }
    fn secret(&self, name: &str) -> Result<Zeroizing<String>> {
        if !self.config.secrets.contains_key(name) {
            return Err(Error("unknown_secret"));
        }
        self.store.get(name)
    }
    fn path(&self, path: &Path) -> PathBuf {
        self.base.join(path)
    }
    pub fn catalog(&self) -> Value {
        json!({"namespace":self.config.namespace, "storage": if self.persistent {"os_keyring"} else {"ephemeral"},
            "secrets": self.config.secrets.iter().map(|(name, d)| json!({"ref":format!("asm://{}/{name}",self.config.namespace), "description": d.description})).collect::<Vec<_>>(),
            "operations": self.config.operations.iter().map(|(name, op)| json!({"name":name,"secret_ref":format!("asm://{}/{}",self.config.namespace, op.secret())})).collect::<Vec<_>>()})
    }
    pub fn delete(&mut self, name: &str) -> Result<()> {
        if !self.config.secrets.contains_key(name) {
            return Err(Error("unknown_secret"));
        }
        let _lock = if self.persistent {
            Some(store::lock()?)
        } else {
            None
        };
        self.store.delete(name)
    }
    pub fn execute(&mut self, name: &str) -> Result<Outcome> {
        let op = self
            .config
            .operations
            .get(name)
            .cloned()
            .ok_or(Error("unknown_operation"))?;
        let _lock = if self.persistent {
            Some(store::lock()?)
        } else {
            None
        };
        let status = match &op {
            Operation::Capture {
                secret,
                source,
                replace,
            } => {
                // Check before side effects such as issuing a new API token.
                self.check_write(secret, *replace)?;
                let value = self.capture(source)?;
                self.store.put(secret, &value, *replace)?;
                "stored"
            }
            Operation::Generate {
                secret,
                bytes,
                replace,
            } => {
                self.check_write(secret, *replace)?;
                let mut value = Zeroizing::new(vec![0; *bytes]);
                getrandom::fill(&mut value).map_err(|_| Error("random_generation_failed"))?;
                let encoded =
                    Zeroizing::new(base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(&value));
                self.store.put(secret, &encoded, *replace)?;
                "stored"
            }
            Operation::Deliver {
                secret,
                destination,
            } => {
                let value = self.secret(secret)?;
                self.deliver(destination, &value)?
            }
        };
        Ok(Outcome {
            operation: name.into(),
            secret_ref: format!("asm://{}/{}", self.config.namespace, op.secret()),
            status,
        })
    }
    fn check_write(&self, secret: &str, replace: bool) -> Result<()> {
        if replace {
            return Ok(());
        }
        match self.secret(secret) {
            Ok(_) => Err(Error("secret_already_exists")),
            Err(Error("secret_not_found")) => Ok(()),
            Err(e) => Err(e),
        }
    }
    fn command_env(&self, command: &CommandSpec) -> Result<BTreeMap<String, Zeroizing<String>>> {
        command
            .secret_env
            .iter()
            .map(|(variable, name)| Ok((variable.clone(), self.secret(name)?)))
            .collect()
    }
    fn capture(&self, source: &Source) -> Result<Zeroizing<String>> {
        match source {
            Source::File { path, json_pointer } => {
                let file = crate::open_regular(&self.path(path))?;
                extract(&bounded_read(file)?, json_pointer.as_deref())
            }
            Source::Environment { variable } => crate::validate_secret(
                std::env::var(variable).map_err(|_| Error("source_environment_missing"))?,
            ),
            Source::Command {
                command,
                json_pointer,
            } => extract(
                &process::run(command, &self.command_env(command)?)?,
                json_pointer.as_deref(),
            ),
            Source::Http {
                request,
                json_pointer,
            } => {
                let response = self
                    .request(request, None)?
                    .send()
                    .map_err(|_| Error("http_request_failed"))?;
                if !response.status().is_success() {
                    return Err(Error("http_status_failed"));
                }
                extract(&bounded_read(response)?, Some(json_pointer))
            }
            Source::Browser {
                page,
                selector,
                click,
            } => {
                validate_url(&page.url, self.config.allow_http_loopback)?;
                Browser::connect(page)?.capture(selector, click.as_deref())
            }
        }
    }
    fn deliver(&self, destination: &Destination, value: &str) -> Result<&'static str> {
        match destination {
            Destination::File { path, replace } => {
                let path = self.path(path);
                let parent = path.parent().ok_or(Error("invalid_destination"))?;
                let mut file = tempfile::NamedTempFile::new_in(parent)
                    .map_err(|_| Error("destination_write_failed"))?;
                file.write_all(value.as_bytes())
                    .map_err(|_| Error("destination_write_failed"))?;
                file.as_file()
                    .sync_all()
                    .map_err(|_| Error("destination_write_failed"))?;
                if *replace {
                    file.persist(&path)
                        .map_err(|_| Error("destination_write_failed"))?;
                } else {
                    file.persist_noclobber(&path)
                        .map_err(|_| Error("destination_exists_or_write_failed"))?;
                }
                std::fs::File::open(parent)
                    .and_then(|f| f.sync_all())
                    .map_err(|_| Error("destination_sync_failed"))?;
                Ok("delivered")
            }
            Destination::Command { command, variable } => {
                let mut env = self.command_env(command)?;
                if env
                    .insert(variable.clone(), Zeroizing::new(value.into()))
                    .is_some()
                {
                    return Err(Error("duplicate_environment_binding"));
                }
                process::run(command, &env)?;
                Ok("command_succeeded")
            }
            Destination::Http { request, placement } => {
                let response = self
                    .request(request, Some((placement, value)))?
                    .send()
                    .map_err(|_| Error("http_request_failed"))?;
                if !response.status().is_success() {
                    return Err(Error("http_status_failed"));
                }
                // Do not forward response bodies, even if the server echoes credentials.
                Ok("http_succeeded")
            }
            Destination::Browser {
                page,
                selector,
                submit,
                success_selector,
            } => {
                validate_url(&page.url, self.config.allow_http_loopback)?;
                Browser::connect(page)?.fill(
                    selector,
                    value,
                    submit.as_deref(),
                    success_selector.as_deref(),
                )?;
                Ok(if success_selector.is_some() {
                    "browser_condition_met"
                } else {
                    "delivered"
                })
            }
        }
    }
    fn request(
        &self,
        request: &HttpRequest,
        delivery: Option<(&Placement, &str)>,
    ) -> Result<reqwest::blocking::RequestBuilder> {
        let url = validate_url(&request.url, self.config.allow_http_loopback)?;
        let method = reqwest::Method::from_bytes(request.method.as_bytes())
            .map_err(|_| Error("invalid_http_method"))?;
        let mut builder = http_client()?.request(method, url);
        let mut body = request.json.clone();
        if let Some(auth) = &request.auth {
            let value = self.secret(&auth.secret)?;
            builder = secret_header(builder, &auth.header, &auth.prefix, &value)?;
        }
        if let Some((placement, value)) = delivery {
            match placement {
                Placement::Header { name, prefix } => {
                    builder = secret_header(builder, name, prefix, value)?
                }
                Placement::JsonField { field } => {
                    let object = body
                        .get_or_insert_with(|| json!({}))
                        .as_object_mut()
                        .ok_or(Error("invalid_json_destination"))?;
                    if object.contains_key(field) {
                        return Err(Error("json_field_already_exists"));
                    }
                    object.insert(field.clone(), Value::String(value.into()));
                }
            }
        }
        if let Some(body) = body {
            builder = builder.json(&body);
        }
        Ok(builder)
    }
}

fn secret_header(
    builder: reqwest::blocking::RequestBuilder,
    name: &str,
    prefix: &str,
    value: &str,
) -> Result<reqwest::blocking::RequestBuilder> {
    let name = reqwest::header::HeaderName::from_bytes(name.as_bytes())
        .map_err(|_| Error("invalid_http_header"))?;
    let mut header = reqwest::header::HeaderValue::from_str(&format!("{prefix}{value}"))
        .map_err(|_| Error("invalid_http_header"))?;
    header.set_sensitive(true);
    Ok(builder.header(name, header))
}
pub fn http_client() -> Result<reqwest::blocking::Client> {
    reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(15))
        .connect_timeout(Duration::from_secs(5))
        .redirect(reqwest::redirect::Policy::none())
        .no_proxy()
        .build()
        .map_err(|_| Error("http_client_failed"))
}
pub fn loopback(url: &url::Url) -> bool {
    match url.host() {
        Some(url::Host::Ipv4(ip)) => ip.is_loopback(),
        Some(url::Host::Ipv6(ip)) => ip.is_loopback(),
        Some(url::Host::Domain("localhost")) => true,
        _ => false,
    }
}
pub fn validate_url(raw: &str, allow_http_loopback: bool) -> Result<url::Url> {
    let url = url::Url::parse(raw).map_err(|_| Error("invalid_http_url"))?;
    if !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
        || url.host().is_none()
        || !(url.scheme() == "https"
            || (allow_http_loopback && url.scheme() == "http" && loopback(&url)))
    {
        return Err(Error("insecure_http_url"));
    }
    Ok(url)
}
pub fn bounded_read(reader: impl Read) -> Result<Zeroizing<Vec<u8>>> {
    let mut bytes = Zeroizing::new(Vec::new());
    reader
        .take((MAX_CAPTURE + 1) as u64)
        .read_to_end(&mut bytes)
        .map_err(|_| Error("capture_read_failed"))?;
    if bytes.len() > MAX_CAPTURE {
        return Err(Error("capture_too_large"));
    }
    Ok(bytes)
}
pub fn extract(bytes: &[u8], pointer: Option<&str>) -> Result<Zeroizing<String>> {
    let value = if let Some(pointer) = pointer {
        let parsed: Value =
            serde_json::from_slice(bytes).map_err(|_| Error("invalid_source_json"))?;
        parsed
            .pointer(pointer)
            .and_then(Value::as_str)
            .ok_or(Error("source_field_missing_or_not_string"))?
            .to_owned()
    } else {
        // Remove only the conventional command/file line ending; preserve spaces.
        let text = std::str::from_utf8(bytes).map_err(|_| Error("source_not_utf8"))?;
        text.strip_suffix("\r\n")
            .or_else(|| text.strip_suffix('\n'))
            .unwrap_or(text)
            .to_owned()
    };
    crate::validate_secret(value)
}
