# Guía de instalación de Apptainer en Windows

**Windows + WSL 2 + Ubuntu**

Esta guía instala Apptainer en Ubuntu dentro de WSL 2 y abre el Frontend de ARSOFT en modo demo. No se inician Backend, base de datos ni Agentes.

## Antes de empezar

Necesitas Windows 11 o una versión reciente de Windows 10, conexión a Internet y permisos de administrador para instalar WSL. El Frontend gráfico se muestra mediante WSLg, incluido en Windows 11 y en versiones recientes de WSL.

## 1. Instalar Ubuntu con WSL 2

Abre **PowerShell como administrador** y ejecuta:

```powershell
wsl --install -d Ubuntu-24.04
```

Reinicia el equipo si Windows lo pide. Abre **Ubuntu** desde el menú Inicio y crea el usuario y la contraseña de Linux. Al escribir la contraseña no se muestran caracteres; es normal.

Comprueba que la distribución usa WSL 2, desde PowerShell:

```powershell
wsl -l -v
```

La columna `VERSION` debe indicar `2`.

## 2. Instalar Apptainer

En la terminal de Ubuntu, ejecuta:

```bash
sudo apt update
sudo apt install -y software-properties-common
sudo add-apt-repository -y ppa:apptainer/ppa
sudo apt update
sudo apt install -y apptainer
apptainer version
```

Si aparece un número de versión, Apptainer está instalado.

## 3. Construir solo el Frontend

Abre Ubuntu y ve a la carpeta raíz del repositorio. Por ejemplo:

```bash
cd ~/proyectos/Direccion_de_Proyectos
```

Cambia esa ruta por la ubicación donde tengas el proyecto. Construye únicamente la imagen del Frontend:

```bash
find . -type f -name "*.sh" -not -path "./.git/*" -print0 |
  xargs -0 -r sed -i 's/\r$//'
  
bash apptainer/build-all.sh frontend
```

La primera construcción puede tardar varios minutos.

## 4. Abrir y comprobar la demo

En la misma terminal de Ubuntu, fuerza el modo simulado y arranca la interfaz:

```bash
unset ARSOFT_API_URL
bash apptainer/run-frontend.sh
```

Debe aparecer la ventana gráfica del Frontend. El modo demo simula las respuestas localmente; no necesita API, Backend, base de datos, Agentes ni servicios externos. Esta guía comprueba que la aplicación abre correctamente.

Para cerrarla, cierra la ventana o vuelve a la terminal y pulsa `Ctrl+C`.

## Si no aparece la ventana

Comprueba que Windows tiene WSL actualizado. En PowerShell ejecuta `wsl --update`, reinicia Ubuntu y vuelve a lanzar el paso 4. El comando `echo $DISPLAY` dentro de Ubuntu debe mostrar una dirección.

## Enlaces oficiales

- WSL: https://learn.microsoft.com/windows/wsl/install
- Instalación de Apptainer: https://apptainer.org/docs/admin/main/installation.html
