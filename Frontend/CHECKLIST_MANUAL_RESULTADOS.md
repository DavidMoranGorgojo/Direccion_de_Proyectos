# Resultados del checklist manual del Frontend

Hoja de ejecución de [`CHECKLIST_MANUAL.md`](CHECKLIST_MANUAL.md) para entregar a Documentación.
Los pasos y el comportamiento esperado de cada caso están en el checklist; aquí solo se anota el resultado.

## Datos de la ejecución

| Campo | Valor |
|---|---|
| Fecha | |
| Ejecutado por | |
| Ayuda de | |
| Commit / paquete probado | |
| Equipo (SO, Apptainer) | |
| Modo | ☐ Simulado  ☐ Real |
| `ARSOFT_API_URL` | |
| Usuarios de prueba usados | |
| LLM | ☐ Simulado  ☐ Real |

## Cómo rellenarla

- **Resultado**: `OK`, `FALLO` o `N/A` (con motivo en Observaciones). `OK*` = comprobado el 24-11 y repetido el 25-11 con el `main` actual arrancando la interfaz real (PySide6, sin pantalla, modo simulado) y mirando las capturas: **pendiente de confirmar a ojo y, cuando haya servidor, con el servidor real**. Un `OK` sin asterisco solo se marca tras verlo en pantalla.
- **Cobertura automática**: indica qué test de `Test/test_Frontend` ya cubre la lógica del caso. **No sustituye** la prueba manual: los tests no miran el aspecto real de la ventana ni usan el servidor real. Los tests de ventanas y componentes usan un sustituto de Qt (no dibujan nada): por eso los casos visuales se han comprobado además arrancando la interfaz real sin pantalla.
- **Condición**: lo que hace falta preparar antes. Agrupa los casos para ejecutarlos por tandas (ver el orden recomendado más abajo).
- Cada `FALLO` lleva su incidencia en la tabla final (pantalla, pasos, esperado, obtenido, captura).

## 1. Inicio de sesión

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| LG-01 | Ninguna | `test_login_renderizado_inicial` | OK* | OK (24-11, simulado, Qt sin pantalla): logo, usuario, contraseña, botón «Entrar», foco en usuario. El checklist decía «Iniciar sesión»: corregido en el checklist. |
| LG-02 | Ninguna | `test_login_validacion_campos_vacios_muestra_error` | OK* | OK (simulado, Qt sin pantalla): mensaje «Introduce tu usuario y tu contraseña.». El checklist citaba otro texto: corregido. Borde de error no comprobado a ojo. |
| LG-03 | Ninguna | `test_login_toggle_visibilidad_contrasena` | OK* | OK (simulado, Qt sin pantalla): alterna oculto/visible y el botón cambia Mostrar/Ocultar. |
| LG-04 | Ninguna | `test_login_limpieza_error_al_escribir` | OK* | OK (simulado, Qt sin pantalla). |
| LG-05 | Servidor | `test_login_credenciales_incorrectas`, `test_error_401_en_login_credenciales_invalidas` | | |
| LG-06 | Servidor; bloquea el usuario unos minutos | `test_login_429_tras_demasiados_intentos`, `test_error_429_en_login_simulado` | | |
| LG-07 | URL con puerto inactivo | `test_backend_caido_da_error_de_conexion` | | |
| LG-08 | Servidor y usuario válido | `test_app_flujo_login_a_chat_y_logout`, `test_login_resultado_exitoso_emite_senal_y_limpia_clave` | OK* | OK solo en simulado (demo/demo1234). Falta con servidor real. |

## 2. Ventana principal y navegación

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| WN-01 | Sesión iniciada | `test_main_window_renderizado_elementos_cabecera` | OK* | OK (simulado, Qt sin pantalla): «👤 demo», logo y «Cerrar sesión». |
| WN-02 | Probar en modo simulado y en real | `test_modo`, `test_modo_automatico` (solo la lógica del modo) | OK* | OK en simulado (aviso amarillo abajo a la izquierda). Falta ver el modo real. |
| WN-03 | Usuario sin chats | `test_ctr006_historial_vacio_por_entorno`, `test_main_window_estado_vacio_al_abrir_chat_sin_mensajes` | | |
| WN-04 | Usuario con chats | `test_main_window_ordenacion_conversaciones_por_fecha`, `test_ctr006_lectura_historial_por_defecto` | OK* | OK solo en simulado: lista «Temperatura del motor» (15/01/2026) y los chats nuevos por fecha, el más reciente primero. Falta con servidor real. |
| WN-05 | Usuario con 2 o más chats | `test_main_window_seleccion_conversacion_actualiza_interfaz` | | |
| WN-06 | Ninguna | `test_main_window_nuevo_chat_crea_uno_si_el_actual_tiene_mensajes`, `test_main_window_nuevo_chat_reutiliza_vacio_existente` | | |
| WN-07 | Chat persistido (en simulado, «Temperatura del motor»; en real, uno del servidor) | `test_main_window_renombrar_y_borrar_actualizan_el_historial`, `test_ctr006_renombrar_chat_usa_patch_y_parsea_respuesta`, `test_ctr006_renombrar_rechaza_titulo_vacio_o_demasiado_largo` | | Los iconos de editar y borrar se ven en la lista (captura del 25-11). Falta probar la acción. |
| WN-08 | Chat persistido | `test_main_window_renombrar_y_borrar_actualizan_el_historial`, `test_ctr006_eliminar_chat_usa_delete_y_acepta_204`, `test_renombrar_y_borrar_chat_desde_cliente_frontend` | | Probar primero cancelar y luego confirmar. |

## 3. Envío y flujo de consultas

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| CH-01 | Ninguna | `test_main_window_filtro_enter_y_shift_enter` | OK* | OK (simulado, Qt sin pantalla): Enter envía y vacía el campo. |
| CH-02 | Ninguna | `test_main_window_filtro_enter_y_shift_enter` | OK* | OK (simulado, Qt sin pantalla): Shift+Enter inserta salto de línea sin enviar. |
| CH-03 | Ninguna | `test_main_window_envio_ignora_texto_vacio` | OK* | OK (simulado, Qt sin pantalla). |
| CH-04 | Chat nuevo | `test_main_window_envio_mensaje_valido_y_generacion_titulo`, `test_main_window_envio_mensaje_largo_recorta_titulo_con_puntos_suspensivos` | OK* | OK (simulado, Qt sin pantalla): título de 40 caracteres + «…». |
| CH-05 | Ninguna | `test_chat_message_burbuja_usuario`, `test_pregunta_se_conserva_exacta` | OK* | OK (simulado, Qt sin pantalla): burbuja a la derecha con el texto exacto. |
| CH-06 | Respuesta lenta para verlo | `test_chat_message_burbuja_escribiendo` | | |
| CH-07 | Ninguna | `test_main_window_recepcion_respuesta_elimina_typing_y_actualiza_chat` | OK* | OK (simulado, Qt sin pantalla): se retira «escribiendo», se añade la respuesta, el campo recupera el foco. |
| CH-08 | Servidor | `test_primer_mensaje_con_id_vacio_historial_y_continuacion`, `test_ctr006_continuar_chat_con_su_conversacion_id` | | |

## 4. Tipos de respuesta y citas

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| RS-01 | Servidor y LLM | `test_ctr001_respuesta_fundamentada_con_fuentes`, `test_chat_message_renderizado_fuentes` | | |
| RS-02 | Servidor y LLM | `test_ctr001_aclaracion_por_pregunta_demasiado_corta` | OK* | OK solo en simulado: badge «Necesito más datos», sin fuentes. |
| RS-03 | Servidor y LLM | `test_ctr001_sin_evidencia` | OK* | OK solo en simulado: badge «Sin evidencia en la documentación», sin fuentes. |
| RS-04 | Servidor y LLM | `test_ctr001_fuera_de_ambito` | OK* | OK solo en simulado: badge «Fuera de ámbito» con el texto esperado. |
| RS-05 | Necesita una cita a un documento obsoleto en el índice | `test_source_card_marca_documento_obsoleto` | | |
| RS-06 | Parar Agentes o Backend | `test_agentes_caido`, `test_error_500_en_consulta`, `test_chat_message_badges_estados_asistente` | | |

## 5. Valoración 👍 / 👎

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| VL-01 | Servidor; respuestas de 3 tipos | `test_respuesta_con_trace_id_tiene_botones`, `test_no_hay_botones_fuera_de_estado_respuesta`, `test_no_hay_botones_en_usuario_ni_en_typing` | | |
| VL-02 | Servidor | `test_valoracion_correcta_queda_guardada_y_marcada`, `test_cuerpo_y_ruta_enviados` | | |
| VL-03 | Servidor | `test_se_puede_cambiar_la_valoracion`, `test_repetir_el_mismo_valor_no_envia_nada` | | |
| VL-04 | Servidor | `test_la_valoracion_sobrevive_al_cambiar_de_chat` | | |
| VL-05 | Parar el Backend | `test_si_falla_vuelve_al_valor_anterior_y_muestra_texto`, `test_sin_conexion` | | |
| VL-06 | Provocar el límite del Backend | `test_429_demasiadas_valoraciones` | | |
| VL-07 | Invalidar el token | `test_sesion_caducada_cierra_sesion`, `test_401_y_403_son_sesion_caducada` | | |

## 6. Sesión

| ID | Condición | Cobertura automática | Resultado | Observaciones |
|---|---|---|:---:|---|
| SS-01 | Ninguna | `test_app_flujo_login_a_chat_y_logout` | | |
| SS-02 | Respuesta lenta, o renombrado o borrado en curso | `test_main_window_logout_bloqueado_si_ocupado` | | |
| SS-03 | Invalidar el token | `test_sesion_caducada_avisa_y_cierra_sesion`, `test_error_401_en_consulta_indica_sesion_caducada`, `test_token_manipulado_da_sesion_caducada` | | |
| SS-04 | Dos usuarios en el servidor | `test_chat_de_otro_usuario_no_se_puede_usar` | | |

## Orden de ejecución recomendado

1. **Sin servidor** (modo simulado, usuario `demo` / `demo1234`): LG-01 a LG-04, LG-07, WN-01 a WN-03, WN-06 a WN-08, CH-01 a CH-05.
2. **Con servidor y LLM real**: LG-05, LG-08, WN-04, WN-05, CH-06 a CH-08, RS-01 a RS-05, VL-01 a VL-04, SS-01, SS-02, SS-04.
3. **Casos que alteran el servidor o el usuario** (hacerlos al final): LG-06 (bloquea el login), VL-06 (límite de valoraciones), SS-03 y VL-07 (invalidar token), RS-06 y VL-05 (parar Backend o Agentes).

Capturas de pantalla finales para el manual: login, historial, respuesta con citas, aclaración, sin evidencia, fuera de ámbito, valoración, sesión caducada y error de conexión.

## Resumen

| Resultado | Casos |
|---|:---:|
| OK | |
| FALLO | |
| N/A | |
| Total | 41 |

## Incidencias

| Nº | Caso | Pantalla | Pasos | Esperado | Obtenido | Captura | Responsable |
|---|---|---|---|---|---|---|---|
| | | | | | | | |
