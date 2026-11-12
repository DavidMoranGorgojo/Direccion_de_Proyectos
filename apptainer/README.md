# ARSOFT con Apptainer

PostgreSQL y FastAPI se ejecutan como instancias de Apptainer en Ubuntu WSL2. El frontend PySide6 se puede abrir en Windows o desde WSLg. Ingesta se ejecuta bajo demanda y Agentes tiene un adaptador HTTP para Agente 1.

## Arranque local

Desde PowerShell, abre Ubuntu en la raíz del repositorio.

```powershell
wsl -d Ubuntu --cd /mnt/c/Users/jaime/Proyectos/Direccion_de_Proyectos
```

Usa un archivo privado para `DATABASE_URL`, `AGENTES_URL` y `ARSOFT_SERVICE_TOKEN`, además de las credenciales de PostgreSQL. Usa el mismo token aleatorio en el archivo de entorno de Agentes. Si reutilizas `~/.config/arsoft/local.env`, conserva sus credenciales y añade el token antes de reiniciar el Backend. Puedes generar el token con `openssl rand -hex 32`.

```bash
export ARSOFT_LOCAL_ENV="$HOME/.config/arsoft/local.env"
bash apptainer/build-all.sh postgres backend agentes
bash apptainer/start-local.sh
```

Si `arsoft-api` sigue ejecutando la versión anterior, detenla antes del nuevo arranque con `apptainer instance stop arsoft-api`. PostgreSQL conserva sus datos en `~/arsoft-state/postgres`.

En otra terminal, usa el archivo privado de Agentes basado en `.env.agentes.example` y ejecuta la imagen con Ollama disponible y el modelo configurado.

```bash
apptainer run --cleanenv --env-file "$HOME/.config/arsoft/agentes.env" \
  "$HOME/arsoft-images/agentes.sif" --serve
```

`/health` comprueba FastAPI, `/ready` comprueba las dependencias y `/docs` muestra las rutas. PySide6 usa la demo local con `ARSOFT_API_URL` vacía. El flujo conectado queda protegido hasta que se implemente el verificador de sesiones de CTR-005. Para detener los servicios, cierra Agentes con Ctrl+C y ejecuta `bash apptainer/stop-local.sh`.

## Frontend e ingesta

```bash
bash apptainer/build-all.sh frontend ingesta
bash apptainer/run-frontend.sh
ARSOFT_MANUALES_DIR=/ruta/a/los/manuales bash apptainer/run-ingesta.sh
```

El comando de ingesta carga el índice en PostgreSQL. Añade `--sin-embeddings` para extraer solo fragmentos. Los resultados y la caché quedan en `~/arsoft-state`.

## Agentes en Slurm

Prepara un archivo privado con el token compartido y la URL de Ollama en el nodo de cómputo. Ajusta cuenta, partición y QOS según el clúster. Mantén los puertos internos en loopback y usa los túneles autorizados para acceder a ellos.

```bash
export ARSOFT_AGENTS_IMAGE="$HOME/arsoft-images/agentes.sif"
export ARSOFT_AGENTS_ENV="$HOME/.config/arsoft/agentes.env"
export ARSOFT_MODEL_CACHE="$HOME/arsoft-models"
sbatch apptainer/cluster/agentes.sbatch
```

[Enlaces y notas para los contratos](INTEGRACION_CONTRATOS.md)
