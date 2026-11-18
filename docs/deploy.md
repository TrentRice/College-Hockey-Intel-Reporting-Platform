# Deploying the public site

CHIRP's dashboard runs publicly on a free Oracle Cloud server, at a free DuckDNS address
over HTTPS. The server runs the same Docker stack as the Mac, plus **Caddy**, which is the
only thing the internet can reach:

```
visitor ──HTTPS──► Caddy (:80, :443) ──Docker network──► Dashboard ──► API ──► Postgres
                    public                                 127.0.0.1 only on the server
```

- **What's public:** the dashboard only. It has no login, so anyone with the address sees
  everything on it.
- **What isn't:** the API and the database. They keep their `127.0.0.1` ports, so only the
  server itself can reach them.
- **Same pipeline:** the nightly refresh, prediction logging and backups run on the server
  just as they did on the Mac.

The files involved are [docker-compose.prod.yml](../docker-compose.prod.yml) (adds Caddy and
requires a real database password), [deploy/Caddyfile](../deploy/Caddyfile) and
[deploy/duckdns.sh](../deploy/duckdns.sh).

**Cost:** $0. Oracle's Always Free tier covers the server, and DuckDNS and Let's Encrypt
(Caddy's certificates) are free.

## 1. Create the Oracle Cloud account

1. Sign up at <https://www.oracle.com/cloud/free/>. It asks for a credit card to verify
   you, but Always Free resources are never charged.
2. Pick your **home region** carefully, because it can't be changed later and Always Free
   servers only run there. Choose one near you. If the busiest US regions (Ashburn, Phoenix)
   often say "out of capacity," a quieter one such as US Midwest (Chicago) can work better.
3. Stay on the free account. Don't upgrade to Pay As You Go unless you've read what it
   charges for.

## 2. Create the server

In the Oracle console, go to **Compute → Instances → Create instance**:

| Setting | Value |
|---|---|
| Name | `chirp` |
| Image | **Canonical Ubuntu 24.04** (click *Change image*) |
| Shape | *Change shape* → **Ampere** → `VM.Standard.A1.Flex`, **2 OCPUs, 12 GB memory** (Always Free covers up to 4 and 24) |
| Networking | Create a new virtual cloud network and a **public subnet**, and keep **Assign a public IPv4 address** on |
| SSH keys | **Upload public key**: your Mac's `~/.ssh/id_ed25519.pub` (if you have none, make one with `ssh-keygen -t ed25519`) |
| Boot volume | Default (about 47 GB, free) |

Click **Create**. If it says **"Out of capacity"**, try another *availability domain* on
the same page, or retry later; free ARM capacity comes and goes.

When the instance is running, copy its **Public IP address** from the instance page.

## 3. Open ports 80 and 443 in Oracle's firewall

Oracle blocks everything except SSH by default. On the instance page, click the
**subnet** → **Security** (or *Security Lists*) → the default security list → **Add
Ingress Rules**, and add three rules, each with source CIDR `0.0.0.0/0`:

| IP protocol | Destination port |
|---|---|
| TCP | 80 |
| TCP | 443 |
| UDP | 443 |

Leave port 22 (SSH) as it is. **Never open 5432, 8000 or 8501.**

## 4. Set up the server

From your Mac:

```bash
ssh ubuntu@<public-ip>
```

On the server:

```bash
# Updates, plus git and make
sudo apt update && sudo apt upgrade -y
sudo apt install -y git make

# Oracle's Ubuntu image has its own firewall (iptables) on top of step 3: allow web traffic
sudo iptables -I INPUT -p tcp -m multiport --dports 80,443 -m conntrack --ctstate NEW -j ACCEPT
sudo iptables -I INPUT -p udp --dport 443 -m conntrack --ctstate NEW -j ACCEPT
sudo netfilter-persistent save

# Docker (official install script), and let the ubuntu user run it
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

SSH back in so the Docker group takes effect, then check with `docker run --rm hello-world`.

## 5. Get a DuckDNS address

1. Go to <https://www.duckdns.org> and sign in (GitHub, Google and others work).
2. Add a subdomain, e.g. `chirp`, which gives you `chirp.duckdns.org`.
3. Put the server's public IP in its **current ip** box and click **update ip**.
4. Copy your **token** from the top of the page for step 7.

Check it from your Mac: `ping chirp.duckdns.org` should show the server's IP.

## 6. Get the code and settings onto the server

On the server:

```bash
git clone https://github.com/TrentRice/College-Hockey-Intel-Reporting-Platform.git chirp
cd chirp
cp .env.example .env
openssl rand -hex 32   # run twice: one for the database password, one for the API key
nano .env
```

In `.env`, set:

```bash
POSTGRES_PASSWORD=<first random value>
DATABASE_URL=postgresql://hockey:<first random value>@localhost:5432/hockey
API_KEY=<second random value>
DOMAIN=chirp.duckdns.org
```

Use a new password and API key here, not the ones from your Mac. **Set the database password
before the first start**: Postgres keeps the password it's created with.

### Bring the prediction log over

The prediction log is the one thing the server can't rebuild from College Hockey News. On
your **Mac**:

```bash
make backup   # writes data/backups/predictions_<today>.csv.gz
scp data/backups/predictions_*.csv.gz ubuntu@<public-ip>:chirp/data/backups/
```

### Let the containers write their folders

The containers run as user `10001`, and on Linux (unlike Docker Desktop on the Mac) that user
needs to own the folders it writes. Back on the **server**, in `~/chirp`:

```bash
mkdir -p logs
sudo chown -R 10001:10001 data logs
```

## 7. Keep DuckDNS pointed at the server

The server's IP normally stays the same, but this updates DuckDNS automatically if it ever
changes. On the server:

```bash
printf 'DUCKDNS_DOMAIN=chirp\nDUCKDNS_TOKEN=<your token>\n' > ~/.duckdns
chmod 600 ~/.duckdns
~/chirp/deploy/duckdns.sh && cat ~/.duckdns.log   # should print OK
(crontab -l 2>/dev/null; echo "*/5 * * * * $HOME/chirp/deploy/duckdns.sh") | crontab -
```

## 8. Start it

```bash
cd ~/chirp
make prod-up        # builds the images (a few minutes the first time) and starts everything
make prod-restore   # loads the prediction log you copied over
make prod-refresh   # first data load: scrapes CHN and fills the database
```

Then open **https://chirp.duckdns.org**. The first visit can take a few seconds while
Caddy gets its certificate.

The nightly refresh starts by itself after 5 a.m. Eastern (on Mondays only, May–August), just
as on the Mac. If a run is already going, `make prod-refresh` says so and doesn't start a
second one.

### If the first refresh fails

Some sites block cloud servers. If `make prod-refresh` fails while downloading from College
Hockey News (connection refused, 403, or timeouts), look at `logs/` and `make prod-runs`. The
fallback is to keep scraping on the Mac and copy the data to the server; ask before setting
that up.

## 9. Turn off the Mac's copy

Once the site works, stop the Mac's nightly pipeline so College Hockey News isn't scraped
twice a day. On the Mac:

```bash
docker compose stop pipeline   # or `make down` to stop the whole local stack
```

The Mac stack still works for development: `make up` starts it again.

## Day to day on the server

| Command (in `~/chirp`) | What it does |
|---|---|
| `git pull && make prod-up` | Deploy the latest code from GitHub |
| `make prod-logs` | Follow all the containers' logs |
| `make prod-runs` | Recent refresh runs and their status |
| `make prod-refresh` | Refresh the data now |
| `make prod-down` | Stop the site (data is kept) |

**Backups:** the nightly run writes the prediction-log backup to `~/chirp/data/backups/` on
the server, which is the only copy. Pull it to your Mac now and then:

```bash
scp 'ubuntu@<public-ip>:chirp/data/backups/*' data/backups/
```

**Oracle's idle rule:** Oracle can reclaim Always Free servers that sit almost completely
idle for a week. The nightly pipeline and visitors usually keep it busy enough, and the
backups above cover the prediction log if it happens anyway.

## Security notes

- Only ports 22, 80 and 443 are open, and only Caddy listens on 80 and 443.
- The API key, database password and DuckDNS token live only in `~/chirp/.env` and
  `~/.duckdns` on the server, never in git.
- The containers keep their hardening: non-root users, read-only filesystems, and all Linux
  capabilities dropped. Caddy is given back only the right to use ports 80 and 443.
- Run `sudo apt update && sudo apt upgrade -y` now and then for security updates.
