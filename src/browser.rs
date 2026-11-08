use crate::{Error, Result, config::BrowserPage};
use serde_json::{Value, json};
use std::{
    net::{IpAddr, SocketAddr, TcpStream},
    time::{Duration, Instant},
};
use tungstenite::{Message, WebSocket};
use zeroize::Zeroizing;

pub struct Browser {
    socket: WebSocket<TcpStream>,
    id: u64,
    url: String,
    timeout: Duration,
}

impl Browser {
    pub fn connect(page: &BrowserPage) -> Result<Self> {
        if !(1..=60).contains(&page.timeout_seconds) {
            return Err(Error("invalid_browser_config"));
        }
        let endpoint =
            url::Url::parse(&page.endpoint).map_err(|_| Error("invalid_browser_endpoint"))?;
        if endpoint.scheme() != "http"
            || !crate::engine::loopback(&endpoint)
            || !endpoint.username().is_empty()
            || endpoint.password().is_some()
        {
            return Err(Error("invalid_browser_endpoint"));
        }
        let list = endpoint
            .join("/json/list")
            .map_err(|_| Error("invalid_browser_endpoint"))?;
        let response = crate::engine::http_client()?
            .get(list)
            .send()
            .map_err(|_| Error("browser_unavailable"))?;
        if !response.status().is_success() {
            return Err(Error("browser_unavailable"));
        }
        let bytes = crate::engine::bounded_read(response)?;
        let targets: Value =
            serde_json::from_slice(&bytes).map_err(|_| Error("invalid_browser_response"))?;
        let matches: Vec<_> = targets
            .as_array()
            .ok_or(Error("invalid_browser_response"))?
            .iter()
            .filter(|t| t["type"] == "page" && t["url"].as_str() == Some(page.url.as_str()))
            .collect();
        if matches.len() != 1 {
            return Err(Error("browser_page_not_unique"));
        }
        let ws_url = matches[0]["webSocketDebuggerUrl"]
            .as_str()
            .ok_or(Error("invalid_browser_response"))?;
        let ws = url::Url::parse(ws_url).map_err(|_| Error("invalid_browser_response"))?;
        if ws.scheme() != "ws"
            || !crate::engine::loopback(&ws)
            || ws.port_or_known_default() != endpoint.port_or_known_default()
        {
            return Err(Error("invalid_browser_response"));
        }
        let host = ws
            .host_str()
            .ok_or(Error("invalid_browser_response"))?
            .trim_matches(['[', ']']);
        let ip: IpAddr = if host == "localhost" {
            "127.0.0.1".parse().unwrap()
        } else {
            host.parse()
                .map_err(|_| Error("invalid_browser_response"))?
        };
        let timeout = Duration::from_secs(page.timeout_seconds);
        let socket = TcpStream::connect_timeout(
            &SocketAddr::new(
                ip,
                ws.port_or_known_default()
                    .ok_or(Error("invalid_browser_response"))?,
            ),
            timeout,
        )
        .map_err(|_| Error("browser_unavailable"))?;
        socket
            .set_nonblocking(true)
            .map_err(|_| Error("browser_io_failed"))?;
        let config = tungstenite::protocol::WebSocketConfig::default()
            .max_message_size(Some(crate::MAX_CAPTURE))
            .max_frame_size(Some(crate::MAX_CAPTURE));
        let start = Instant::now();
        let mut handshake = tungstenite::client::client_with_config(ws_url, socket, Some(config));
        let (socket, _) = loop {
            match handshake {
                Ok(socket) => break socket,
                Err(tungstenite::HandshakeError::Interrupted(mid)) => {
                    pause(start, timeout)?;
                    handshake = mid.handshake();
                }
                Err(_) => return Err(Error("browser_connect_failed")),
            }
        };
        Ok(Self {
            socket,
            id: 0,
            url: page.url.clone(),
            timeout,
        })
    }

    fn eval(&mut self, body: &str) -> Result<Value> {
        self.id += 1;
        let expression = format!(
            "(() => {{ if (location.href !== {}) throw new Error('wrong_page'); {} }})()",
            json!(self.url),
            body
        );
        let request = json!({"id": self.id, "method":"Runtime.evaluate", "params": {"expression":expression, "returnByValue":true}});
        self.socket
            .get_mut()
            .set_nonblocking(true)
            .map_err(|_| Error("browser_io_failed"))?;
        let start = Instant::now();
        match self.socket.send(Message::Text(request.to_string().into())) {
            Ok(()) => (),
            Err(e) if would_block(&e) => (),
            Err(_) => return Err(Error("browser_io_failed")),
        }
        loop {
            match self.socket.flush() {
                Ok(()) => break,
                Err(e) if would_block(&e) => pause(start, self.timeout)?,
                Err(_) => return Err(Error("browser_io_failed")),
            }
        }
        loop {
            if start.elapsed() > self.timeout {
                return Err(Error("browser_timeout"));
            }
            let message = match self.socket.read() {
                Ok(message) => message,
                Err(e) if would_block(&e) => {
                    pause(start, self.timeout)?;
                    continue;
                }
                Err(_) => return Err(Error("browser_io_failed")),
            };
            if let Message::Text(text) = message {
                let response: Value =
                    serde_json::from_str(&text).map_err(|_| Error("invalid_browser_response"))?;
                if response["id"] == self.id {
                    if response.get("error").is_some()
                        || response["result"].get("exceptionDetails").is_some()
                    {
                        return Err(Error("browser_action_failed"));
                    }
                    return response["result"]["result"]
                        .get("value")
                        .cloned()
                        .ok_or(Error("browser_action_failed"));
                }
            }
        }
    }

    fn click(&mut self, selector: &str) -> Result<()> {
        self.eval(&format!("const e = document.querySelector({}); if (!e) throw new Error('missing'); e.click(); return true;", json!(selector)))?;
        Ok(())
    }

    pub fn capture(&mut self, selector: &str, click: Option<&str>) -> Result<Zeroizing<String>> {
        let read = format!(
            "const e = document.querySelector({}); return e ? (('value' in e) ? e.value : e.textContent) : null;",
            json!(selector)
        );
        let previous = if click.is_some() {
            self.eval(&read)?
                .as_str()
                .map(|s| Zeroizing::new(s.to_owned()))
        } else {
            None
        };
        if let Some(click) = click {
            self.click(click)?;
        }
        let start = Instant::now();
        loop {
            let value = self.eval(&read)?;
            if let Some(value) = value
                .as_str()
                .filter(|s| !s.is_empty() && previous.as_ref().map(|p| p.as_str()) != Some(*s))
            {
                return crate::validate_secret(value.to_owned());
            }
            if start.elapsed() >= self.timeout {
                return Err(Error("browser_capture_timeout"));
            }
            std::thread::sleep(Duration::from_millis(50));
        }
    }

    pub fn fill(
        &mut self,
        selector: &str,
        value: &str,
        submit: Option<&str>,
        success_selector: Option<&str>,
    ) -> Result<()> {
        self.eval(&format!("const e = document.querySelector({}); if (!(e instanceof HTMLInputElement || e instanceof HTMLTextAreaElement)) throw new Error('invalid_target'); const p = e instanceof HTMLInputElement ? HTMLInputElement.prototype : HTMLTextAreaElement.prototype; Object.getOwnPropertyDescriptor(p, 'value').set.call(e, {}); e.dispatchEvent(new Event('input', {{bubbles:true}})); e.dispatchEvent(new Event('change', {{bubbles:true}})); return true;", json!(selector), json!(value)))?;
        if let Some(submit) = submit {
            self.click(submit)?;
        }
        if let Some(selector) = success_selector {
            let start = Instant::now();
            loop {
                if self.eval(&format!(
                    "return document.querySelector({}) !== null;",
                    json!(selector)
                ))? == true
                {
                    break;
                }
                if start.elapsed() >= self.timeout {
                    return Err(Error("browser_verification_timeout"));
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
        Ok(())
    }
}

fn would_block(error: &tungstenite::Error) -> bool {
    matches!(error, tungstenite::Error::Io(e) if e.kind() == std::io::ErrorKind::WouldBlock)
}

fn pause(start: Instant, timeout: Duration) -> Result<()> {
    if start.elapsed() >= timeout {
        return Err(Error("browser_timeout"));
    }
    std::thread::sleep(Duration::from_millis(5));
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    #[test]
    fn incomplete_websocket_frame_cannot_extend_deadline() {
        let listener = std::net::TcpListener::bind("127.0.0.1:0").unwrap();
        let address = listener.local_addr().unwrap();
        let sender = std::thread::spawn(move || {
            let (socket, _) = listener.accept().unwrap();
            let mut websocket = tungstenite::accept(socket).unwrap();
            websocket.read().unwrap();
            let stream = websocket.get_mut();
            stream.write_all(&[0x81, 126, 3, 232]).unwrap();
            for _ in 0..40 {
                if stream.write_all(b" ").is_err() {
                    break;
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        });
        let stream = TcpStream::connect(address).unwrap();
        stream
            .set_read_timeout(Some(Duration::from_secs(1)))
            .unwrap();
        let (socket, _) = tungstenite::client(format!("ws://{address}"), stream).unwrap();
        let mut browser = Browser {
            socket,
            id: 0,
            url: "https://example.com".into(),
            timeout: Duration::from_secs(1),
        };
        let start = Instant::now();
        let result = browser.eval("return true;");
        drop(browser);
        sender.join().unwrap();
        assert_eq!(result, Err(Error("browser_timeout")));
        assert!(start.elapsed() < Duration::from_millis(1800));
    }
}
