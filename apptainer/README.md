# ARSOFT con Apptainer

PostgreSQL con pgvector y FastAPI se ejecutan como instancias de Apptainer en Ubuntu WSL2. PySide6 se abre en la sesión gráfica y la ingesta se lanza bajo demanda. Agentes se puede ejecutar como consola en local. El despliegue del servicio HTTP de Agentes se reserva para Slurm con GPU.

## Preparación y arranque local

Desde PowerShell, abre Ubuntu en la raíz del repositorio:

```powershell
wsl -d Ubuntu --cd /mnt/c/Users/jaime/Proyectos/Direccion_de_Proyectos
```

En Bash dentro de Ubuntu:

```bash
cp -n apptainer/.env.local.example apptainer/.env.local
# Edita POSTGRES_PASSWORD y DATABASE_URL.
bash apptainer/build-all.sh postgres backend
bash apptainer/start-local.sh
bash apptainer/stop-local.sh
```

También puedes mantener el archivo de configuración privado en el sistema de archivos de Linux y exportar `ARSOFT_LOCAL_ENV` con su ruta. Por defecto, las imágenes se guardan en `~/arsoft-images` y PostgreSQL conserva sus datos en `~/arsoft-state/postgres`. El esquema se inicializa en el primer arranque. El script comprueba la conexión a PostgreSQL con las credenciales configuradas, la tabla de fragmentos, la extensión pgvector y la respuesta de FastAPI en `/health`. La API actual solo expone ese endpoint de ARSOFT.

## Frontend e ingesta

```bash
bash apptainer/build-all.sh frontend ingesta
bash apptainer/run-frontend.sh
ARSOFT_MANUALES_DIR=/ruta/a/los/manuales bash apptainer/run-ingesta.sh --sin-embeddings
```

El frontend se abre con WSLg y usa el modo simulado por defecto. `ARSOFT_API_URL` activa la conexión a un Backend con los endpoints de la interfaz. La ingesta monta los PDF en solo lectura y conserva los resultados y la caché en `~/arsoft-state/ingesta/salida` y `~/arsoft-state/cache/huggingface`. El comando sin argumentos usa `--cargar`. En el código actual esa opción escribe directamente en PostgreSQL con `DATABASE_URL`; el contrato para delegar esa escritura al Backend queda pendiente.

## Agentes y Slurm

```bash
bash apptainer/build-all.sh agentes
apptainer run --cleanenv "$HOME/arsoft-images/agentes.sif"
```

La consola de Agente 1 usa el simulador de Agente 2 y puede requerir un motor LLM accesible según su configuración. Para Slurm, prepara un archivo de entorno compatible con `apptainer --env-file` a partir de `.env.agentes.example`. Define `AGENTES_START_CMD` cuando exista el servidor HTTP de Agentes y ajusta cuenta, partición y QOS según el clúster.

```bash
export ARSOFT_AGENTS_IMAGE="$HOME/arsoft-images/agentes.sif"
export ARSOFT_AGENTS_ENV="$HOME/arsoft-secrets/agentes.env"
export ARSOFT_MODEL_CACHE="$HOME/arsoft-models"
sbatch apptainer/cluster/agentes.sbatch
```

Para una integración remota por túneles autorizados, el Backend local usa `AGENTES_URL` y el proceso en el nodo de cómputo usa `BACKEND_URL`. PostgreSQL permanece en el loopback local. Slurm detiene Agentes cuando termina la asignación.
