# ARSOFT con Apptainer

PostgreSQL, Backend y Agentes se ejecutan como instancias de Apptainer en Ubuntu/WSL2. El comando de arranque también ejecuta la ingesta si encuentra PDF y abre el Frontend PySide6 mediante WSLg.

## Arrancar todo junto (Ubuntu / WSL2)

El comando único se ejecuta desde la raíz del repositorio, dentro de Ubuntu/WSL2 con Apptainer y WSLg:

~~~bash
bash apptainer/start-all.sh
~~~

En el primer uso genera ~/.config/arsoft/local.env y agentes.env con permisos privados, construye las imágenes SIF que falten y arranca PostgreSQL con pgvector, Backend y Agentes. Después comprueba login e historial y abre el Frontend conectado al Backend. Cierra la ventana o pulsa Ctrl+C: el comando detiene las instancias que él mismo inició y conserva la base de datos, las imágenes y las cachés de modelos.

La ingesta es un proceso puntual. De forma automática indexa PDF nuevos en data/manuales; puedes indicar otra ruta al lanzar el mismo comando:

~~~bash
ARSOFT_MANUALES_DIR=/ruta/a/los/manuales bash apptainer/start-all.sh
~~~

Si no encuentra PDF, avisa y continúa con la prueba básica de login, historial e interfaz. Ollama debe estar levantado para generar respuestas; los PDF y los modelos de recuperación son necesarios para comprobar el RAG. El arranque no inventa respuestas ni corpus de prueba.

Las credenciales de usuario demo se crean en el entorno local (usuario1 / usuario123). Para no crearlas, configura ARSOFT_SEED_DEV_USERS=0 en local.env; las contraseñas son públicas y nunca deben usarse en producción. Los secretos del servicio se generan automáticamente en una instalación nueva; si editas los archivos de entorno, conserva el mismo ARSOFT_SERVICE_TOKEN en ambos.

Para detener servicios que hayas arrancado manualmente: `bash apptainer/stop-local.sh`.

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
