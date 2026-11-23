# ARSOFT con Apptainer

PostgreSQL y FastAPI se ejecutan como instancias de Apptainer en Ubuntu WSL2. El frontend PySide6 se puede abrir en Windows o desde WSLg. Ingesta se ejecuta bajo demanda y Agentes tiene un adaptador HTTP para Agente 1.

## Arrancar todo junto

Orden completo para ejecutar el Frontend en modo real, desde Ubuntu (WSL2). Cada bloque indica en qué terminal va.

1. **Preparar la configuración privada (una vez).** Copia las plantillas y rellena credenciales y token (`openssl rand -hex 32`); el mismo token va en los dos archivos.

   ```bash
   mkdir -p ~/.config/arsoft && chmod 700 ~/.config/arsoft
   cp apptainer/.env.local.example ~/.config/arsoft/local.env
   cp apptainer/.env.agentes.example ~/.config/arsoft/agentes.env
   ```

2. **Construir las imágenes (una vez, o tras cambiar código).**

   ```bash
   bash apptainer/build-all.sh postgres backend agentes frontend
   ```

3. **Terminal 1: PostgreSQL y Backend.**

   ```bash
   export ARSOFT_LOCAL_ENV="$HOME/.config/arsoft/local.env"
   bash apptainer/start-local.sh
   apptainer exec instance://arsoft-api python -m app.usuarios_prueba --desarrollo   # solo desarrollo
   ```

4. **Terminal 2: Agentes** (con Ollama en marcha y el modelo descargado). Usa el comando de la sección *Arranque local*.

5. **Terminal 3: Frontend en modo real.** Entra con `usuario1` / `usuario123`.

   ```bash
   ARSOFT_API_URL=http://127.0.0.1:8000 bash apptainer/run-frontend.sh
   ```

   Sin `ARSOFT_API_URL` abre la demo simulada. El script solo pasa al contenedor las variables del Frontend (`ARSOFT_MODO`, `ARSOFT_API_URL`, `ARSOFT_LOGIN_PATH`, `ARSOFT_HISTORIAL_PATH`, `ARSOFT_CONSULTA_PATH`, `ARSOFT_TIMEOUT_S`, `ARSOFT_ALLOW_HTTP`, `ARSOFT_MOCK_EMPTY_HISTORY`).

6. **Comprobar.** `curl http://127.0.0.1:8000/health` (Backend) y `/ready` (PostgreSQL y Agentes).

7. **Parar.** Cierra el Frontend, `Ctrl+C` en Agentes y `bash apptainer/stop-local.sh`.

## Arranque local

Desde PowerShell, abre Ubuntu en la raíz del repositorio.

```powershell
wsl -d Ubuntu --cd /ruta/al/repositorio/Direccion_de_Proyectos
```

Usa un archivo privado para `AGENTES_URL`, `ARSOFT_SERVICE_TOKEN` y las credenciales de PostgreSQL. Los scripts construyen `DATABASE_URL` con esas credenciales. Usa el mismo token aleatorio en el archivo de entorno de Agentes. Si reutilizas `~/.config/arsoft/local.env`, conserva sus credenciales y añade el token antes de reiniciar el Backend. Puedes generar el token con `openssl rand -hex 32`.

```bash
export ARSOFT_LOCAL_ENV="$HOME/.config/arsoft/local.env"
bash apptainer/build-all.sh postgres backend agentes
bash apptainer/start-local.sh
```

Si `arsoft-api` sigue ejecutando la versión anterior, detenla antes del nuevo arranque con `apptainer instance stop arsoft-api`. PostgreSQL conserva sus datos en `~/arsoft-state/postgres`.

En otra terminal, usa el archivo privado de Agentes basado en `.env.agentes.example` y ejecuta la imagen con Ollama disponible y el modelo configurado.

```bash
mkdir -p "$HOME/arsoft-state/agents/huggingface" "$HOME/arsoft-state/agents/state"
chmod 700 "$HOME/arsoft-state/agents/state"
apptainer run --cleanenv --env-file "$HOME/.config/arsoft/agentes.env" \
  --bind "$HOME/arsoft-state/agents:/models" \
  "$HOME/arsoft-images/agentes.sif" --serve
```

`/health` comprueba FastAPI, `/ready` comprueba las dependencias y `/docs` muestra las rutas. PySide6 usa la demo local con `ARSOFT_API_URL` vacía. El flujo conectado exige sesión (CTR-005): crea los usuarios de prueba con `apptainer exec instance://arsoft-api python -m app.usuarios_prueba --desarrollo` (solo en desarrollo) y entra con ellos (ver `Backend/readme.md`). El esquema `aplicacion` (usuarios, chats, mensajes y registro) lo crea `Backend/db/init/02_usuarios.sql` al iniciar una base nueva; en una base ya creada, ejecútalo una vez con `psql`. Para detener los servicios, cierra Agentes con Ctrl+C y ejecuta `bash apptainer/stop-local.sh`.

## Frontend e ingesta

```bash
bash apptainer/build-all.sh frontend ingesta
bash apptainer/run-frontend.sh
ARSOFT_MANUALES_DIR=/ruta/a/los/manuales bash apptainer/run-ingesta.sh
```

El comando de ingesta carga el índice en PostgreSQL. Añade `--sin-embeddings` para extraer solo fragmentos. Los resultados y la caché quedan en `~/arsoft-state`.

## Paquete final del Frontend

El paquete es un `.tar.gz` autosuficiente: solo necesita Apptainer y una sesión gráfica en la máquina de destino.

```bash
bash apptainer/package-frontend.sh             # usa ~/arsoft-images/frontend.sif si existe
bash apptainer/package-frontend.sh --rebuild   # reconstruye la imagen antes (pide sudo)
```

Genera en `dist/` (fuera de git) `arsoft-frontend-<AAAAMMDD>-<commit>.tar.gz` y su `.sha256`. Dentro: `frontend.sif`, `run-frontend.sh`, `verificar.sh`, `SHA256SUMS` y `LEEME.txt`.

En la máquina de destino (por ejemplo, una Ubuntu o WSL2 limpia con Apptainer instalado según [`GUIA_INSTALACION_WINDOWS.md`](GUIA_INSTALACION_WINDOWS.md)):

```bash
sha256sum -c arsoft-frontend-*.tar.gz.sha256
tar -xzf arsoft-frontend-*.tar.gz && cd arsoft-frontend-*/
bash verificar.sh        # Apptainer, DISPLAY, sumas, arranque sin ventana y limpieza de la imagen
bash run-frontend.sh     # demo; con ARSOFT_API_URL=... abre el modo real
```

La imagen se construye desde `Frontend/apptainer/frontend.def` y no incluye `__pycache__`, `.vscode` ni `.env`. Su fase `%test` comprueba al construir que Qt y la configuración cargan.

## Agentes en Slurm

Prepara un archivo privado con el token compartido y la URL de Ollama en el nodo de cómputo. Ajusta cuenta, partición y QOS según el clúster. Mantén los puertos internos en loopback y usa los túneles autorizados para acceder a ellos.

```bash
export ARSOFT_AGENTS_IMAGE="$HOME/arsoft-images/agentes.sif"
export ARSOFT_AGENTS_ENV="$HOME/.config/arsoft/agentes.env"
export ARSOFT_MODEL_CACHE="$HOME/arsoft-models"
sbatch apptainer/cluster/agentes.sbatch
```

[Enlaces y notas para los contratos](INTEGRACION_CONTRATOS.md)
