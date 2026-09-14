{{- define "haeron-backend.fullname" -}}
{{ .Values.backend.name }}
{{- end -}}

{{- define "haeron-backend.labels" -}}
app: {{ .Values.backend.name }}
{{- end -}}