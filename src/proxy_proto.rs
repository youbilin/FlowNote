//! 解析 Xray freedom 出站 `proxyProtocol` 发来的 PROXY 头(v1 文本 / v2 二进制),
//! 取出"真实来源地址"。头部长度是自描述的,所以精确读取、不会多吞 HTTP 数据。

use anyhow::{anyhow, bail, Result};
use std::net::{IpAddr, Ipv4Addr, Ipv6Addr, SocketAddr};
use tokio::io::{AsyncRead, AsyncReadExt};

const V2_SIG: [u8; 12] = *b"\r\n\r\n\0\r\nQUIT\n";
const V2_MAX_BODY: usize = 536;

/// 返回 `Some(来源地址)`;LOCAL / UNKNOWN / 非 TCP 返回 `None`。
pub async fn read_header<R: AsyncRead + Unpin>(r: &mut R) -> Result<Option<SocketAddr>> {
    let mut first = [0u8; 1];
    r.read_exact(&mut first).await?;
    match first[0] {
        b'P' => read_v1(r).await,
        0x0D => read_v2(r).await,
        b => bail!("不是 PROXY 协议头(首字节 0x{b:02x})"),
    }
}

async fn read_v1<R: AsyncRead + Unpin>(r: &mut R) -> Result<Option<SocketAddr>> {
    let mut line = vec![b'P'];
    loop {
        if line.len() >= 107 {
            bail!("PROXY v1 头过长");
        }
        let mut b = [0u8; 1];
        r.read_exact(&mut b).await?;
        line.push(b[0]);
        if line.ends_with(b"\r\n") {
            break;
        }
    }
    parse_v1(&line)
}

pub fn parse_v1(line: &[u8]) -> Result<Option<SocketAddr>> {
    let s = std::str::from_utf8(line)?.trim_end();
    let mut it = s.split(' ');
    if it.next() != Some("PROXY") {
        bail!("PROXY v1 头格式错误");
    }
    match it.next() {
        Some("UNKNOWN") => Ok(None),
        Some("TCP4") | Some("TCP6") => {
            let src: IpAddr = it.next().ok_or_else(|| anyhow!("缺少源地址"))?.parse()?;
            let _dst: IpAddr = it.next().ok_or_else(|| anyhow!("缺少目的地址"))?.parse()?;
            let sport: u16 = it.next().ok_or_else(|| anyhow!("缺少源端口"))?.parse()?;
            Ok(Some(SocketAddr::new(src, sport)))
        }
        other => bail!("不支持的 PROXY v1 协议族: {other:?}"),
    }
}

async fn read_v2<R: AsyncRead + Unpin>(r: &mut R) -> Result<Option<SocketAddr>> {
    let mut head = [0u8; 16];
    head[0] = 0x0D;
    r.read_exact(&mut head[1..]).await?;
    let len = u16::from_be_bytes([head[14], head[15]]) as usize;
    if len > V2_MAX_BODY {
        bail!("PROXY v2 头过长: {len}");
    }
    let mut body = vec![0u8; len];
    r.read_exact(&mut body).await?;
    parse_v2(&head, &body)
}

pub fn parse_v2(head: &[u8; 16], body: &[u8]) -> Result<Option<SocketAddr>> {
    if head[..12] != V2_SIG {
        bail!("PROXY v2 签名错误");
    }
    if head[12] >> 4 != 2 {
        bail!("PROXY 版本不是 2");
    }
    match head[12] & 0x0F {
        0 => return Ok(None), // LOCAL
        1 => {}               // PROXY
        c => bail!("未知 PROXY 命令 {c}"),
    }
    let (fam, proto) = (head[13] >> 4, head[13] & 0x0F);
    if proto != 1 {
        return Ok(None); // 只处理 TCP(STREAM)
    }
    match fam {
        1 => {
            if body.len() < 12 {
                bail!("PROXY v2 IPv4 地址块过短");
            }
            let ip = Ipv4Addr::new(body[0], body[1], body[2], body[3]);
            let port = u16::from_be_bytes([body[8], body[9]]);
            Ok(Some(SocketAddr::new(IpAddr::V4(ip), port)))
        }
        2 => {
            if body.len() < 36 {
                bail!("PROXY v2 IPv6 地址块过短");
            }
            let mut o = [0u8; 16];
            o.copy_from_slice(&body[..16]);
            let port = u16::from_be_bytes([body[32], body[33]]);
            Ok(Some(SocketAddr::new(IpAddr::V6(Ipv6Addr::from(o)), port)))
        }
        _ => Ok(None),
    }
}

/// 把 ::ffff:1.2.3.4 之类折叠成 IPv4,保证和日志里的写法一致。
pub fn canon(a: SocketAddr) -> SocketAddr {
    SocketAddr::new(a.ip().to_canonical(), a.port())
}

#[cfg(test)]
mod tests {
    use super::*;

    fn v2_ipv4(src: [u8; 4], sport: u16) -> Vec<u8> {
        let mut v = V2_SIG.to_vec();
        v.push(0x21); // v2 + PROXY
        v.push(0x11); // IPv4 + STREAM
        v.extend_from_slice(&12u16.to_be_bytes());
        v.extend_from_slice(&src);
        v.extend_from_slice(&[127, 0, 0, 1]);
        v.extend_from_slice(&sport.to_be_bytes());
        v.extend_from_slice(&8686u16.to_be_bytes());
        v
    }

    #[tokio::test]
    async fn v2_ipv4_ok() {
        let mut data: &[u8] = &v2_ipv4([203, 0, 113, 5], 51234);
        let got = read_header(&mut data).await.unwrap();
        assert_eq!(got, Some("203.0.113.5:51234".parse().unwrap()));
    }

    #[tokio::test]
    async fn v2_does_not_overread_payload() {
        let mut bytes = v2_ipv4([1, 2, 3, 4], 80);
        bytes.extend_from_slice(b"GET / HTTP/1.1\r\n");
        let mut data: &[u8] = &bytes;
        read_header(&mut data).await.unwrap();
        assert_eq!(data, b"GET / HTTP/1.1\r\n");
    }

    #[tokio::test]
    async fn v2_ipv6_ok() {
        let mut v = V2_SIG.to_vec();
        v.push(0x21);
        v.push(0x21); // IPv6 + STREAM
        v.extend_from_slice(&36u16.to_be_bytes());
        v.extend_from_slice(&"2001:db8::1".parse::<Ipv6Addr>().unwrap().octets());
        v.extend_from_slice(&"::1".parse::<Ipv6Addr>().unwrap().octets());
        v.extend_from_slice(&40000u16.to_be_bytes());
        v.extend_from_slice(&8686u16.to_be_bytes());
        let mut data: &[u8] = &v;
        let got = read_header(&mut data).await.unwrap();
        assert_eq!(got, Some("[2001:db8::1]:40000".parse().unwrap()));
    }

    #[tokio::test]
    async fn v2_local_is_none() {
        let mut v = V2_SIG.to_vec();
        v.push(0x20);
        v.push(0x00);
        v.extend_from_slice(&0u16.to_be_bytes());
        let mut data: &[u8] = &v;
        assert_eq!(read_header(&mut data).await.unwrap(), None);
    }

    #[tokio::test]
    async fn v1_tcp4_ok_and_no_overread() {
        let mut data: &[u8] = b"PROXY TCP4 198.51.100.7 127.0.0.1 40001 8686\r\nGET / HTTP/1.1\r\n";
        let got = read_header(&mut data).await.unwrap();
        assert_eq!(got, Some("198.51.100.7:40001".parse().unwrap()));
        assert_eq!(data, b"GET / HTTP/1.1\r\n");
    }

    #[tokio::test]
    async fn v1_unknown_is_none() {
        let mut data: &[u8] = b"PROXY UNKNOWN\r\n";
        assert_eq!(read_header(&mut data).await.unwrap(), None);
    }

    #[tokio::test]
    async fn garbage_rejected() {
        let mut data: &[u8] = b"GET / HTTP/1.1\r\n\r\n";
        assert!(read_header(&mut data).await.is_err());
    }

    #[test]
    fn canon_folds_mapped_v4() {
        let a: SocketAddr = "[::ffff:1.2.3.4]:99".parse().unwrap();
        assert_eq!(canon(a), "1.2.3.4:99".parse::<SocketAddr>().unwrap());
    }
}
