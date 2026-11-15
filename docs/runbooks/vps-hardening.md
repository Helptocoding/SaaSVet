# Runbook — VPS hardening (Ubuntu 24.04)

Capa 5 del plan de despliegue VPS (`DEPLOY_VPS_PLAN.md`, retirado del árbol en `8886604`; se consulta con `git show 8886604^:DEPLOY_VPS_PLAN.md`). Esto NO es código del repo — son comandos a correr UNA VEZ en el VPS recién aprovisionado, antes del primer `docker compose up`.

**Audiencia**: vos (o el on-call). Asumir cero conocimiento previo del host.

**Tiempo estimado**: 1-2h primera vez.

---

## 0. Pre-requisitos antes de tocar el VPS

| # | Requisito | Cómo |
|---|-----------|------|
| 0.1 | Cuenta en provider VPS | Hetzner / Vultr / DO / Linode |
| 0.2 | VPS provisionado: **Ubuntu 24.04 LTS**, 2 vCPU, 4 GB RAM, 40 GB SSD | Panel del provider |
| 0.3 | IPv4 pública del VPS anotada | Email/panel del provider |
| 0.4 | Acceso SSH inicial — usuario `root` + password O tu SSH key ya cargada en el panel | Depende del provider. Hetzner permite ambos; DO pide SSH key al crear |
| 0.5 | Llave SSH ed25519 generada en tu laptop | Ver §0.A si no tienes |
| 0.6 | Dominio comprado + DNS apuntando al IPv4 del VPS (A record) | Cloudflare / Namecheap / GoDaddy. Propagación 1-5 min |

### 0.A — Generar SSH key en tu laptop (si no tienes)

> **Warning**: NO uses la passphrase vacía si tu laptop puede ser robada. Recomendado: passphrase + agente SSH cacheando.

```bash
# En TU laptop (Windows con Git Bash / macOS / Linux):
ssh-keygen -t ed25519 -C "tu-email@dominio.com" -f ~/.ssh/vet_vps

# Esto crea ~/.ssh/vet_vps (privada — NUNCA compartir) y ~/.ssh/vet_vps.pub
cat ~/.ssh/vet_vps.pub   # ← copiar este contenido (empieza con "ssh-ed25519 AAAA...")
```

Si el provider pide pegar la public key al crear el VPS, pega ahí el contenido de `vet_vps.pub`. Saltea §1 password login si ya quedó cargada.

---

## 1. Primer SSH al VPS

Reemplazar `<VPS_IP>` por tu IP real.

```bash
# Si el provider te dio password root (Hetzner default):
ssh root@<VPS_IP>
# (paste password — único uso, vas a desactivar password auth en §3)

# Si el provider ya cargó tu SSH key (DO / Vultr con key):
ssh -i ~/.ssh/vet_vps root@<VPS_IP>
```

**Smoke check inicial** dentro del VPS:
```bash
hostnamectl              # Operating System: Ubuntu 24.04 LTS
free -h                  # RAM total ≥ 4Gi
df -h /                  # Disco / ≥ 30G free
ip -4 addr show eth0     # Confirmar IP pública
```

---

## 2. Crear user `deploy` (no operar como root)

```bash
adduser deploy
# Te pide password — usa uno fuerte (lo necesitarás solo para `sudo`)
# El resto de campos (Full Name, etc.) puedes dejar vacíos con Enter

usermod -aG sudo deploy

# Copiar la SSH key que ya usaste para entrar como root:
mkdir -p /home/deploy/.ssh
cp ~/.ssh/authorized_keys /home/deploy/.ssh/   # si entraste con key
# O si entraste con password, pegar la public key manualmente:
#   nano /home/deploy/.ssh/authorized_keys
#   (pegar contenido de TU vet_vps.pub)

chown -R deploy:deploy /home/deploy/.ssh
chmod 700 /home/deploy/.ssh
chmod 600 /home/deploy/.ssh/authorized_keys
```

**CRÍTICO — Verificar acceso `deploy` ANTES de seguir**:

> **Warning**: Abre OTRA terminal en tu laptop (sin cerrar la sesión root actual). Si el siguiente paso falla y desactivas password auth en §3, te quedas fuera del VPS para siempre.

```bash
# En OTRA terminal de tu laptop:
ssh -i ~/.ssh/vet_vps deploy@<VPS_IP>
# DEBE entrar sin pedir password (sudo SÍ pedirá password el primer uso por terminal)

# Una vez dentro, probar sudo:
sudo whoami     # → root
```

Si esto NO funciona, NO sigas. Revisa permisos de `authorized_keys` y el contenido pegado.

---

## 3. Endurecer SSH (irreversible si te cortas)

> **Warning**: Este paso es IRREVERSIBLE si te equivocas. Mantén tu sesión actual abierta + otra sesión `deploy` paralela viva durante TODO el proceso. Si SSH se rompe, NO PIERDES esas sesiones — puedes editar y revertir desde ahí.

Como root (todavía en la sesión inicial):

```bash
# Backup primero
cp /etc/ssh/sshd_config /etc/ssh/sshd_config.bak

# Editar — usar sed para evitar errores de tipeo manual:
sed -i \
  -e 's/^#*PermitRootLogin.*/PermitRootLogin no/' \
  -e 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' \
  -e 's/^#*PubkeyAuthentication.*/PubkeyAuthentication yes/' \
  -e 's/^#*ChallengeResponseAuthentication.*/ChallengeResponseAuthentication no/' \
  -e 's/^#*KbdInteractiveAuthentication.*/KbdInteractiveAuthentication no/' \
  /etc/ssh/sshd_config

# Validar sintaxis ANTES de restart
sshd -t && echo "config OK"

# Aplicar (NO cierra tu sesión actual — solo afecta NUEVAS conexiones)
systemctl restart ssh
```

**Verificación obligatoria** desde una TERCERA terminal en tu laptop:

```bash
# Debe FALLAR (rechazo password):
ssh -o PreferredAuthentications=password -o PubkeyAuthentication=no deploy@<VPS_IP>
# Expected: "Permission denied (publickey)."

# Debe FALLAR (root bloqueado):
ssh -i ~/.ssh/vet_vps root@<VPS_IP>
# Expected: "Permission denied (publickey)."

# Debe ENTRAR (deploy con key):
ssh -i ~/.ssh/vet_vps deploy@<VPS_IP>
```

Si los 3 checks pasan, cierra la sesión root inicial. De ahora en adelante: `ssh -i ~/.ssh/vet_vps deploy@<VPS_IP>` siempre.

Si algo falla, NO cierres las sesiones viejas — revierte:
```bash
cp /etc/ssh/sshd_config.bak /etc/ssh/sshd_config
systemctl restart ssh
```

---

## 4. Firewall UFW

Como `deploy` con sudo:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing

sudo ufw allow 22/tcp    comment 'ssh'
sudo ufw allow 80/tcp    comment 'http (Caddy ACME challenge + redirect to https)'
sudo ufw allow 443/tcp   comment 'https'
sudo ufw allow 443/udp   comment 'http3 quic'

sudo ufw --force enable

sudo ufw status verbose
```

Esperado en `status verbose`:
```
Status: active
Default: deny (incoming), allow (outgoing)

22/tcp                     ALLOW IN    Anywhere    # ssh
80/tcp                     ALLOW IN    Anywhere    # http ...
443/tcp                    ALLOW IN    Anywhere    # https
443/udp                    ALLOW IN    Anywhere    # http3 quic
```

**Verificación**: Postgres :5432 NO debe estar accesible desde internet:
```bash
# Desde TU laptop:
nc -zv <VPS_IP> 5432   # debe timeout / connection refused
nc -zv <VPS_IP> 22     # debe succeed
```

---

## 5. Auto-updates de seguridad + fail2ban

```bash
sudo apt update
sudo apt upgrade -y                                  # primer upgrade completo
sudo apt install -y unattended-upgrades fail2ban

# Configurar unattended-upgrades — solo security updates auto, NUNCA reboots
sudo dpkg-reconfigure -plow unattended-upgrades
# Acepta "Yes" para habilitar

# Verificar que el timer está activo
systemctl status apt-daily.timer apt-daily-upgrade.timer
```

`fail2ban` arranca con defaults razonables para SSH. Verificar:
```bash
sudo systemctl status fail2ban
sudo fail2ban-client status sshd
```

---

## 6. Docker + compose plugin

> **Warning**: NUNCA `apt install docker.io` — esa es la versión vieja de Ubuntu. Usa el script oficial de Docker.

```bash
# Install Docker Engine oficial
curl -fsSL https://get.docker.com | sudo sh

# Permitir a `deploy` correr docker sin sudo
sudo usermod -aG docker deploy

# Compose plugin (Docker oficial ya incluye, esto es por si acaso)
sudo apt install -y docker-compose-plugin

# RE-LOGIN para que el grupo docker tome efecto en tu shell
exit
ssh -i ~/.ssh/vet_vps deploy@<VPS_IP>

# Verificar (sin sudo)
docker version
docker compose version
docker run --rm hello-world
```

`hello-world` debe imprimir `Hello from Docker!`. Si pide sudo, no re-logueaste — `exit` + `ssh` de nuevo.

---

## 7. Log rotation Docker

Sin esto, los logs de los containers crecen sin límite y llenan `/var/lib/docker/containers/*/`-`-json.log` hasta saturar el disco.

```bash
sudo tee /etc/docker/daemon.json > /dev/null <<'EOF'
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "5"
  }
}
EOF

# Aplicar
sudo systemctl restart docker

# Verificar
docker info | grep -A2 "Logging Driver"
# Debe mostrar:
#   Logging Driver: json-file
```

Aplica solo a containers NUEVOS. Si ya hubiera containers viejos sin esta config, recreate (`docker compose down && up`) para que tomen el log driver.

---

## 8. Swap (si RAM < 8 GB)

Buffer para picos de memoria + Postgres + gunicorn. 2 GB es estándar para VPS 4 GB.

```bash
# Sanity check antes
free -h
swapon --show     # vacío = no hay swap

# Crear archivo 2GB
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile

# Persistir en fstab
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab

# Tuning: priorizar RAM sobre swap (Postgres se degrada feo en swap)
echo 'vm.swappiness=10' | sudo tee -a /etc/sysctl.d/99-vet.conf
sudo sysctl -p /etc/sysctl.d/99-vet.conf

# Verificar
free -h
# Debe mostrar Swap: 2.0Gi total
```

---

## 9. Timezone host = UTC

Postgres + Django + logs en UTC = cero ambigüedad cuando correlacionas eventos. Las conversiones a TZ del cliente (México) las hace Django con `TIME_ZONE = 'UTC'` + `USE_TZ = True` en `settings.py`.

```bash
sudo timedatectl set-timezone UTC
sudo systemctl restart systemd-timesyncd

# Verificar
timedatectl
# Debe mostrar:
#   Time zone: UTC (UTC, +0000)
#   System clock synchronized: yes
#   NTP service: active
```

---

## 10. Crear directorios del proyecto

```bash
# Para que el clone + .env.prod + backups vivan en path estable
sudo mkdir -p /opt/vet
sudo chown deploy:deploy /opt/vet

sudo mkdir -p /var/backups/vet
sudo chown deploy:deploy /var/backups/vet
```

Esto deja listos los paths que las Capas 6 y 9 esperan (`/opt/vet/app` para el clone, `/var/backups/vet` para los dumps).

---

## 11. Checklist final de verificación

Ejecutar TODOS desde sesión `deploy`:

```bash
# Identidad y permisos
whoami                                  # deploy
id                                      # uid=1000(deploy) gid=1000(deploy) groups=...sudo,docker
sudo whoami                             # root (tras password)

# SSH lockdown
sudo grep -E '^(PermitRootLogin|PasswordAuthentication|PubkeyAuthentication)' /etc/ssh/sshd_config
# Esperado:
#   PermitRootLogin no
#   PasswordAuthentication no
#   PubkeyAuthentication yes

# Firewall
sudo ufw status | grep -c "ALLOW IN"    # >= 4 (22, 80, 443 tcp, 443 udp)

# Auto-updates
systemctl is-active apt-daily.timer apt-daily-upgrade.timer
# Ambos: active

# fail2ban
sudo fail2ban-client status sshd | grep "Currently failed"
# 0 (todavía nadie atacó)

# Docker
docker compose version | grep -c "Docker Compose version"   # 1
docker info | grep -i "Logging Driver: json-file"           # match
docker ps                                                   # tabla vacía OK

# Swap
free -h | grep -i swap | awk '{print $2}'   # 2.0Gi

# Timezone
timedatectl | grep "Time zone"              # UTC

# Project dirs
ls -ld /opt/vet /var/backups/vet
# Ambos owned by deploy:deploy
```

Si TODOS los checks pasan = VPS listo para clonar el repo y arrancar la app (Capa 9).

---

## 12. Gotchas comunes

| Síntoma | Causa | Fix |
|---------|-------|-----|
| `ssh deploy@vps` pide password en vez de usar key | Permisos `authorized_keys` malos | `chmod 700 ~/.ssh && chmod 600 ~/.ssh/authorized_keys` |
| `docker: permission denied` | No re-logueaste tras `usermod -aG docker` | `exit` + `ssh` de nuevo |
| `apt: command not found` post hardening | Te equivocaste de OS al provisionar (CentOS / Alpine) | Wipe + reprovisionar Ubuntu 24.04 |
| Backups crons no corren | `crontab -e` ejecutado como `root` en vez de `deploy` | `sudo crontab -l` vs `crontab -l` |
| Caddy no consigue TLS cert | DNS no propagó / UFW bloquea :80 (necesario para ACME HTTP-01 challenge) | `dig +short app.tu-dominio.com` debe responder VPS IP; `ufw status` debe mostrar 80/tcp ALLOW |
| Postgres container OOM-killed periódicamente | `mem_limit: 1536M` muy ajustado para tu carga | Bajar `GUNICORN_WORKERS` a 2 o agregar `shared_buffers` tuning |
| Disco `/` se llena en días | Logs Docker sin rotation (§7 omitido) o backups locales sin retention | Revisar §7 + `find /var/backups/vet -mtime +14` |

---

## 13. Operaciones recurrentes post-setup

Estas NO son parte de la primera ejecución — son patrones que vas a repetir.

### Update sistema (mensual)

```bash
sudo apt update
sudo apt upgrade -y
sudo apt autoremove -y
# Reboot solo si /var/run/reboot-required existe:
[ -f /var/run/reboot-required ] && sudo reboot
```

### Restart full stack (deploy nuevo)

```bash
cd /opt/vet/app
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod build
docker compose -f docker-compose.prod.yml --env-file .env.prod run --rm release
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

### Acceso emergencia

Si te quedas fuera por algún motivo, casi todos los providers exponen una **web console** (Hetzner: "Console", DO: "Recovery", Vultr: "View Console") que entra al VPS por canal lateral. Desde ahí puedes restaurar SSH o crear un user nuevo. Mantén el password de `deploy` en un password manager — sin password no funciona `sudo` aunque entres por web console.

---

## Siguiente paso

Capa 6 (cron jobs) — `pg-backup.sh` + `flushexpiredtokens` + `build_daily_metrics` + `audit_anchor_integrity`. Esos comandos asumen que `/opt/vet/app` ya tiene el repo clonado + `.env.prod` creado. Eso ocurre en Capa 9 (deploy real). Capa 6 puede mergearse antes (es solo runbook + ejemplo crontab) pero los crons solo arrancan en Capa 9.
