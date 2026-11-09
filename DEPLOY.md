# Deploy no Ubuntu Server (systemd + Caddy)

A API escuta só em `127.0.0.1:8000`; o Caddy recebe 80/443, cuida do HTTPS e repassa para ela.

## Antes de começar

- Python 3.10 ou mais novo (`python3 --version`).
- Para HTTPS: um domínio com registro A (e AAAA, se houver IPv6) apontando para o servidor.
  Se o servidor está em casa, o roteador precisa encaminhar as portas 80 e 443 para ele
  (e, com IP dinâmico, um DNS dinâmico). A porta 80 é necessária para o Caddy validar o certificado.

## 1. Código

    sudo apt update && sudo apt install -y git python3-venv
    sudo useradd --system --home /opt/habitos --shell /usr/sbin/nologin habitos
    sudo mkdir -p /opt/habitos && sudo chown habitos:habitos /opt/habitos
    sudo -u habitos git clone https://github.com/SEU_USUARIO/SEU_REPO.git /opt/habitos
    cd /opt/habitos
    sudo -u habitos python3 -m venv .venv
    sudo -u habitos .venv/bin/pip install -r requirements.txt

## 2. Configuração

    sudo cp deploy/habitos.env.example /etc/habitos.env
    sudo chmod 600 /etc/habitos.env      # edite se quiser mudar fuso, janela etc.

## 3. Serviço

    sudo cp deploy/habitos.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now habitos
    systemctl status habitos
    curl http://127.0.0.1:8000/api/hoje      # deve devolver {"hoje": ..., "fuso": ...}

Logs: `journalctl -u habitos -f`.

## 4. Primeiro token (no servidor; o banco daqui é separado do seu local)

    cd /opt/habitos
    sudo -u habitos env HABITOS_DB=/var/lib/habitos/habitos.db .venv/bin/python -m app.tokens criar web

Guarde o token que aparece, ele não é mostrado de novo. Um token por dispositivo (celular, ESP32...).

## 5. HTTPS com Caddy

Instale o Caddy pelas instruções oficiais para Ubuntu: https://caddyserver.com/docs/install

    sudo nano /etc/caddy/Caddyfile       # conteúdo de deploy/Caddyfile, com o seu domínio
    sudo systemctl reload caddy

## 6. Firewall

    sudo ufw allow OpenSSH
    sudo ufw allow 80/tcp
    sudo ufw allow 443/tcp
    sudo ufw enable

Não libere a 8000: ela só precisa ser acessível pelo próprio servidor.

## 7. Conferir

    curl -i https://SEU_DOMINIO/api/hoje                                   # 200
    curl -i https://SEU_DOMINIO/api/calendarios                            # 401 (sem token)
    curl -H "Authorization: Bearer SEU_TOKEN" https://SEU_DOMINIO/api/calendarios   # 200

Depois abra https://SEU_DOMINIO no navegador e cole o token.

## Atualizar

    cd /opt/habitos
    sudo -u habitos git pull
    sudo -u habitos .venv/bin/pip install -r requirements.txt
    sudo systemctl restart habitos

## Sem domínio ou sem abrir portas

Tailscale (acesso só pelos seus dispositivos, sem domínio) ou Cloudflare Tunnel (exige domínio no Cloudflare)
dispensam o encaminhamento de portas; nesse caso o Caddy não é necessário.
