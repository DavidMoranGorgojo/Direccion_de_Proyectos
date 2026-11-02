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
            if version not in chunk.get("vigente_para", []):
                continue

        if component not in (None, ""):
            if chunk.get("componente") != component:
                continue

        if document_type not in (None, ""):
            if chunk.get("tipo_documento") != document_type:
                continue

        filtered_chunks.append(chunk)

    return filtered_chunks