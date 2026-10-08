# Manual Oficial de Trámites Ciudadanos - Gobierno de El Salvador (Corpus de Referencia)

Este documento constituye el corpus de referencia para el Data Store (`sv-tramites-datastore-{dev,stg,prd}`) en **Gemini Enterprise (Vertex AI Search)** utilizado por el agente No-Code **Asistente de Trámites Ciudadanos**.

---

## 1. Documento Único de Identidad (DUI) - Registro Nacional de las Personas Naturales (RNPN)

### 1.1 Emisión de DUI por Primera Vez (Mayores de 18 años)
- **Requisitos**:
  1. Certificación de Partida de Nacimiento original y reciente (no mayor a 1 año de emisión) o verificación en línea con el sistema del RNPN.
  2. Documento con fotografía (carné estudiantil, pasaporte o cédula) o presentarse acompañado de dos testigos mayores de edad con DUI vigente (o uno de los padres con DUI vigente).
- **Costo oficial**: **$0.00 USD (Trámite totalmente gratuito por ley para la primera emisión)**.
- **Pasos**:
  1. Agendar cita en el portal oficial `https://www.dui.sv` o acudir a cualquier Duicentro del país.
  2. Presentar los documentos requeridos en ventanilla.
  3. Realizar captura de fotografía, huellas dactilares y firma.
  4. Recibir el DUI el mismo día.

### 1.2 Renovación o Reposición de DUI (Por vencimiento, extravío, robo o deterioro)
- **Requisitos**:
  1. Presentar el DUI vencido o deteriorado (en caso de extravío o robo, no es necesario presentar denuncia policial; se verifica la identidad mediante huellas dactilares en el sistema del RNPN).
  2. Comprobante de pago del arancel oficial.
- **Costo oficial**: **$10.31 USD**.
- **Pasos**:
  1. Cancelar el arancel de **$10.31 USD** en línea (`https://www.dui.sv`), puntos Express o bancos autorizados.
  2. Agendar cita en `https://www.dui.sv` y acudir al Duicentro seleccionado.
  3. Verificar datos biométricos, actualizar fotografía si corresponde y retirar el nuevo DUI.

---

## 2. Pasaporte Ordinario - Dirección General de Migración y Extranjería (DGME)

### 2.1 Emisión o Renovación de Pasaporte para Mayores de Edad (Adultos)
- **Requisitos**:
  1. DUI original vigente y en buen estado (si es renovación, presentar además el pasaporte vencido o por vencer).
  2. Comprobante de pago del arancel correspondiente.
- **Costo oficial**: **$25.00 USD** (trámite realizado dentro del territorio de El Salvador).
- **Pasos**:
  1. Realizar el pago de **$25.00 USD** en línea en `https://pasaportes.gob.sv` o en colecturías autorizadas.
  2. Presentarse en la sucursal de la Dirección General de Migración y Extranjería con el DUI original vigente.
  3. Realizar enrolamiento biométrico y toma de fotografía. El pasaporte se entrega el mismo día (en promedio 45 minutos).

### 2.2 Emisión de Pasaporte para Niñas, Niños y Adolescentes (Menores de 18 años)
- **Requisitos**:
  1. Certificación de Partida de Nacimiento original y reciente (vigencia máxima de 1 año).
  2. Presencia física de **ambos padres** con su DUI original vigente.
  3. En caso de que uno de los padres no pueda asistir: presentar **Autorización Notarial (Poder Especial)** otorgada ante notario salvadoreño o Cónsul de El Salvador en el exterior, o resolución judicial de la Procuraduría General de la República (PGR).
  4. Comprobante de pago del arancel.
- **Costo oficial**: **$25.00 USD**.
- **Pasos**:
  1. Pagar el arancel de **$25.00 USD**.
  2. Acudir con el menor de edad y ambos padres (o autorización notarial) a una sucursal de Migración y Extranjería.
  3. Completar la validación documental, captura de fotografía y retiro del pasaporte.

---

## 3. Constancia de Antecedentes Penales - Dirección General de Centros Penales (DGCP)

### 3.1 Solicitud en Línea o Presencial
- **Requisitos**:
  1. DUI original vigente (para salvadoreños) o Pasaporte vigente (para extranjeros).
  2. Cuenta activa en la plataforma gubernamental de Identidad Digital `https://simple.sv` (para trámite en línea).
  3. Pago del arancel oficial.
- **Costo oficial**: **$3.00 USD**.
- **Pasos**:
  1. Ingresar a `https://simple.sv` y seleccionar el trámite "Constancia de Antecedentes Penales".
  2. Completar el formulario y realizar el pago electrónico de **$3.00 USD**.
  3. Descargar la constancia con firma electrónica certificada y código QR verificable, o retirarla en las oficinas de Centros Penales / sedes departamentales.

---

## 4. Renovación de Licencia de Conducir - SERTRACEN / Viceministerio de Transporte (VMT)

### 4.1 Renovación de Licencia de Conducir Vigente o Vencida
- **Requisitos**:
  1. DUI original vigente.
  2. Licencia de conducir anterior (o declaración jurada en SERTRACEN en caso de extravío).
  3. **Estar solvente de esquelas (multas de tránsito) vencidas** ante el Viceministerio de Transporte (VMT) o contar con convenio de pago vigente.
  4. Examen visual aprobado en clínicas autorizadas por SERTRACEN (si aplica por vigencia).
- **Costo oficial**: **$49.14 USD** (costo de emisión del plástico de licencia por 5 años).
- **Pasos**:
  1. Consultar solvencia de esquelas en el sitio web de SERTRACEN (`https://www.sertracen.com.sv`).
  2. Presentar DUI y licencia anterior en cualquier sucursal de SERTRACEN (San Salvador, Santa Ana, San Miguel o Centros Comerciales).
  3. Cancelar **$49.14 USD** y retirar la licencia renovada el mismo día.

---

## 5. Límites de Alcance y Políticas de Seguridad del Asistente Ciudadano

- El Asistente de Trámites Ciudadanos es un **canal exclusivamente informativo y de orientación**.
- **Prohibiciones estrictas**:
  1. No puede anular, exonerar ni modificar multas de tránsito (esquelas) ni aranceles establecidos por ley.
  2. No brinda asesoría jurídica privada ni redacta demandas judiciales o escrituras notariales.
  3. Nunca solicita contraseñas bancarias, números completos de tarjetas de crédito ni códigos OTP a los ciudadanos.
