
def filter_chunks(chunks, filters=None):
    filters = filters or {}

    if not isinstance(filters, dict):
        raise TypeError("filters debe ser un diccionario.")

    version = filters.get("version")
    component = filters.get("componente")
    document_type = filters.get("tipo_documento")

    filtered_chunks = []

    for chunk in chunks:
        if version not in (None, ""):
            versiones = chunk.get("versiones", [])
            vigente_para = chunk.get("vigente_para", [])

            version_aplicable = version in versiones

            # Excepción: documentos sustituidos que siguen
            # siendo aplicables a versiones anteriores.
            if chunk.get("sustituido_por") is not None:
                version_aplicable = (
                    version_aplicable or version in vigente_para
                )

            if not version_aplicable:
                continue

        if component not in (None, ""):
            if chunk.get("componente") != component:
                continue

        if document_type not in (None, ""):
            if chunk.get("tipo_documento") != document_type:
                continue

        filtered_chunks.append(chunk)

    return filtered_chunks
