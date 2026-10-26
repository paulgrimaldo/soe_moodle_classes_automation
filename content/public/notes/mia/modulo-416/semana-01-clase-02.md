# Clase 2: Teoría del Color, Branding Corporativo y DAX Avanzado

> **Objetivo de la Sesión**<br>
> 
> 
> Dominar el uso estratégico del color y el branding corporativo como herramientas de comunicación y dirección de la atención ejecutiva, y profundizar en el modelado semántico avanzado mediante DAX en Power BI, diferenciando columnas calculadas de medidas dinámicas y aplicando la función CALCULATE para derivar métricas de negocio.

---

## 1\. El Color como Herramienta Estratégica de Comunicación

### 1.1. Principio Fundamental: Comunicación vs. Decoración

- El color en la visualización de datos no cumple una función estética o artística, sino una función **cognitiva y comunicacional**.

- **La regla de los tres colores:** Como mejor práctica de diseño analítico, se recomienda **no utilizar más de tres colores dominantes** en un reporte o dashboard. El uso desmedido de colores (el efecto arcoíris) genera fatiga visual, satura al usuario y destruye el mensaje principal.

### 1.2. El Color Gris: El Mejor Aliado del Analista

- **El concepto del lienzo atenuado:** Cuando se presentan múltiples categorías, series temporales o competidores, colorear cada elemento de forma independiente distrae y aburre a la audiencia.

- **Opacar la información de soporte:** El uso del tono gris permite mantener en el gráfico la información contextual necesaria (líneas base, competidores secundarios, periodos previos) sin competir por la atención visual.

- **Dirección deliberada de la mirada:** Al atenuar el contexto en gris y aplicar un color contrastante (azul, verde, naranja o rojo) exclusivamente sobre el punto de interés, el cerebro del tomador de decisiones identifica el insight en milisegundos.

### 1.3. Semántica y Carga Emocional del Color en los Negocios

- **Señales de Alerta y Negatividad (Rojo / Tonos Cálidos):** Utilizados para indicar caídas en el margen, metas no alcanzadas, incrementos en quejas de clientes, pérdidas operativas o saturación de capacidad (*bottlenecks*).

- **Éxito y Desempeño Sobresaliente (Azul / Verde):** Empleados para destacar superación de presupuestos, picos históricos de ventas y cumplimiento de objetivos.

- **Consistencia y Estándares:** Un color neutro consistente para denotar operaciones normales dentro de los rangos de control tolerables.

- **El impacto emocional en la alta gerencia:** Para los fundadores, directores y accionistas, la empresa representa un esfuerzo vital e institucional. Presentar reportes confusos, agresivos o visualmente desordenados distorsiona el diagnóstico de la realidad empresarial.

---

## 2\. Casos de Estudio: Aplicación Práctica del Color

### 2.1. Caso 1: Crecimiento Relativo en Redes Sociales (Enfoque en Insights vs. Volumen Bruto)

- **Escenario:** Análisis de penetración de redes sociales en 2015 respecto a la base de 2012.

- **Problema de visualización:** Facebook dominaba abrumadoramente en volumen absoluto. En un gráfico estándar donde cada red tenía su color corporativo vibrante, Facebook acaparaba toda la atención visual, opacando el verdadero hallazgo analítico.

- **Solución aplicada:** Se atenuaron en gris Facebook, Twitter y LinkedIn. Se resaltaron con color específico únicamente **Pinterest e Instagram**.

- **Mensaje transmitido:** Evidenciar con claridad que Pinterest e Instagram habían duplicado con creces su adopción desde 2012 (crecimiento relativo superior), un insight que quedaba invisible frente a la magnitud bruta de Facebook.

### 2.2. Caso 2: Control de Calidad y Gestión de Reclamos por Ciudad

- **Escenario:** Monitoreo del porcentaje de reclamos por cada 100 pedidos en 20 ciudades de México (periodo 2012-2017).

- **Problema de visualización:** Una matriz de 20 gráficos de barras independientes obliga al directivo a realizar una inspección exhaustiva fila por fila, generando sobrecarga cognitiva y desinterés.

- **Solución aplicada:**

  - Se tiñeron en gris todas las ciudades donde los reclamos se mantuvieron estables o disminuyeron (comportamiento deseado).
  
  - Se resaltó en color de alerta exclusivamente las ciudades donde los reclamos aumentaron (Puebla e Hidalgo).

- **Mensaje transmitido:** El gerente detecta en menos de cinco segundos cuáles son las dos únicas sucursales que requieren auditoría e intervención operativa inmediata.

### 2.3. Caso 3: Justificación de Costos en Infraestructura IT y Cloud Computing

- **Escenario:** Justificar ante el comité financiero la ampliación de instancias de máquinas virtuales y almacenamiento en la nube (AWS / Azure).

- **Reto de comunicación:** Un reporte técnico cargado de cientos de métricas detalladas de hardware (IOPS, hilos de CPU, latencias de red, paginación de memoria) resulta incomprensible e ineficaz para un gerente financiero.

- **Solución aplicada:** Un dashboard puntual con indicadores clave que demuestren que el servidor se encuentra operando al límite de capacidad (*at capacity*). Se utiliza el color para contrastar la capacidad nominal frente a la saturación real, respaldando técnicamente la inversión requerida sin abrumar con tecnicismos.

### 2.4. Caso 4: Inflación Acumulada de Precios en EE.UU. (1997 - 2017)

- **Escenario:** Evolución de precios al consumidor en bienes y servicios durante 20 años.

- **Solución aplicada:** Paleta divergente rojo-azul.

  - **Rojo (Sectores con inflación severa):** Servicios hospitalarios (+200%) y educación superior universitaria (matrículas universitarias inaccesibles).
  
  - **Azul (Sectores deflacionarios o accesibles):** Tecnología de consumo (televisores, software, servicios de telecomunicaciones), donde la innovación y la escala redujeron los precios reales.

### 2.5. Caso 5: Identificación de Nichos y Mercado Potencial en el Sector Construcción

- **Escenario:** Mapeo de subsectores industriales, edificación y construcción con decenas de subcategorías.

- **Solución aplicada:** Opacar en gris todas las actividades secundarias y colorear en un único tono (naranja) las áreas que en conjunto conforman el mercado potencial objetivo (65 millones de pesos), facilitando la justificación comercial del plan de inversión.

---

## 3\. Branding Corporativo y Optimización del Lienzo

### 3.1. Identidad Institucional y Rebranding en Reportes

- Un reporte ejecutivo debe respirar la identidad corporativa de la entidad para la que se diseña:

  - Inclusión sobria del logotipo oficial.
  
  - Adopción de la paleta cromática corporativa (ej. la transición institucional de la UAGRM de rojo/azul tradicional a tonos modernos de azul y blanco).

- Evitar tanto los reportes monocromáticos planos como los fondos oscuros pesados que evocan terminales médicas o radiografías antiguas sin coherencia de negocio.

### 3.2. Comparativas Proyectado vs. Ejecutado (Bullet Charts / OPEX)

- La necesidad universal en los comités ejecutivos radica en contrastar **lo planificado (Budget / Estimado)** contra **lo real ejecutado (Actual / PEX)**.

- Gráficos tipo *Bullet Chart* o barras comparativas bicolores permiten identificar instantáneamente qué departamentos superaron el presupuesto, cuáles alcanzaron la meta y cuáles quedaron rezagados.

### 3.3. Aprovechamiento del Espacio Negativo y Diseño Responsivo

- El espacio en el lienzo de Power BI es un recurso escaso y valioso.

- Los reportes modernos deben concebirse considerando su consumo multiplataforma (pantallas de escritorio y visualización ejecutiva en dispositivos móviles mediante Power BI Service).

- Aprovechar los espacios vacíos para enriquecer el contexto mediante fondos estructurados o tarjetas de síntesis sin saturar el flujo de lectura.

---

## 4\. Laboratorio Práctico: DAX Avanzado y Modelado Semántico en Power BI

### 4.1. Gobierno del Modelo: Columnas Ocultas y Lógica Cerrada

- **Regla de oro de arquitectura analítica:** Todas las columnas numéricas transaccionales y las claves foráneas de la tabla de hechos deben **ocultarse** en la vista de informe.

- **Razón técnica:** Si se dejan visibles en el panel de campos, los usuarios finales pueden arrastrar columnas crudas y aplicarles agregaciones no controladas (promedios, máximos o sumas arbitrarias), desvirtuando la lógica oficial del negocio. El modelo debe consumir exclusivamente **medidas controladas y auditadas**.

### 4.2. Columna Calculada vs. Medida DAX

| Criterio | Columna Calculada (Calculated Column) | Medida DAX (Measure) |
| --- | --- | --- |
| Nivel de Evaluación | Fila por fila (Row Context) en la tabla física. | Agregación dinámica en tiempo de consulta. |
| Momento de Cálculo | Durante la carga y actualización de datos (Refresh). | Bajo demanda al renderizar la visualización. |
| Consumo de Recursos | Almacenamiento persistente en disco y memoria RAM (VertiPaq). | Uso de CPU temporal; no ocupa almacenamiento en el archivo. |
| Sensibilidad a Filtros | Estática: el valor de la fila no cambia con filtros externos. | Dinámica: se recalcula según el Contexto de Filtro (Filter Context). |
| Uso Recomendado | Pre-cálculos granulares, categorizaciones (IF) y filtros dimensionales. | KPIs, sumatorias, conteos, ratios y métricas ejecutivas. |

### 4.3. Implementación de Columnas Precalculadas y Cualificadores de Fila

En la tabla de hechos de ventas (` Orders `), se crearon columnas calculadas para precálculos aritméticos y segmentaciones nominales:

#### 1\. Ventas en Bruto (Gross Sales)

```javascript
Gross Sales = Orders[Quantity] * Orders[List_Price]
```

#### 2\. Ventas Netas con Descuento (Net Sales)

```javascript
Net Sales = Orders[Gross Sales] - (Orders[Gross Sales] * Orders[Discount])
```

#### 3\. Cualificación Nominal del Tipo de Venta (Sales Type)

Permite clasificar cada fila de transacción según el volumen de unidades adquiridas:

```javascript
Sales Type = IF(Orders[Quantity] > 1, "Big Sale", "Normal Sale")
```

#### 4\. Cualificación Nominal del Tipo de Descuento (Discount Type)

Permite segmentar transacciones comerciales agresivas de aquellas con descuentos ordinarios:

```javascript
Discount Type = IF(Orders[Discount] > 0.1, "Big Discount", "Normal Discount")
```

---

### 4.4. Buenas Prácticas: Creación de la Tabla Contenedora de Métricas

En lugar de dispersar las fórmulas dentro de las tablas de datos, se genera una tabla independiente dedicada (ej. ` Metrics ` o ` _Medidas `) mediante la opción *Introducir Datos*. Esto centraliza la lógica del negocio en un repositorio único, ordenado y fácilmente gobernable.

---

### 4.5. Definición de Métricas Primarias (Base)

Las métricas primarias realizan operaciones de agregación elementales sobre las columnas de la tabla de hechos:

#### 1\. Cantidad Total de Unidades Vendidas

```javascript
Total Quantity = SUM(Orders[Quantity])
```

#### 2\. Ingresos Brutos Totales

```javascript
Total Gross Sales = SUM(Orders[Gross Sales])
```

#### 3\. Ingresos Netos Reales

```javascript
Total Net Sales = SUM(Orders[Net Sales])
```

#### 4\. Total de Órdenes Únicas (Manejo de Granularidad)

> **Distinción Crítica: COUNT vs. DISTINCTCOUNT**<br>
> 
> 
> Debido a que la tabla de hechos fue consolidada al nivel de detalle de ítem (cada orden puede tener múltiples filas según la variedad de productos), utilizar un COUNT tradicional contaría líneas de pedido (ítems vendidos). Para obtener el número real de transacciones de compra registradas se debe utilizar DISTINCTCOUNT sobre el identificador de la orden.

```javascript
Total Orders = DISTINCTCOUNT(Orders[Order_ID])
```

---

### 4.6. Métricas Derivadas con Modificación de Contexto (CALCULATE)

La función ` CALCULATE ` es el motor fundamental del lenguaje DAX, ya que permite evaluar una expresión sobreescribiendo o incorporando filtros al contexto de evaluación actual.

#### Derivación por Tipo de Venta (Prorrateo de Volumen e Ingresos)

Permite desglosar el desempeño de ventas grandes frente a ventas unitarias normales:

```javascript
Total Quantity Big Sales = CALCULATE([Total Quantity], Orders[Sales Type] = "Big Sale")

Total Quantity Normal Sales = CALCULATE([Total Quantity], Orders[Sales Type] = "Normal Sale")

Total Net Sales Big Sales = CALCULATE([Total Net Sales], Orders[Sales Type] = "Big Sale")

Total Net Sales Normal Sales = CALCULATE([Total Net Sales], Orders[Sales Type] = "Normal Sale")
```

#### Derivación por Magnitud de Descuento (Análisis de Estrategia Comercial)

Permite evaluar cuánto volumen e ingreso se transó bajo descuentos agresivos:

```javascript
Total Quantity Big Discount = CALCULATE([Total Quantity], Orders[Discount Type] = "Big Discount")

Total Quantity Normal Discount = CALCULATE([Total Quantity], Orders[Discount Type] = "Normal Discount")

Total Net Sales Big Discount = CALCULATE([Total Net Sales], Orders[Discount Type] = "Big Discount")

Total Net Sales Normal Discount = CALCULATE([Total Net Sales], Orders[Discount Type] = "Normal Discount")
```

#### ¿Por qué no derivar Total Orders por Tipo de Venta o Descuento?

Una misma cabecera de orden puede incluir simultáneamente un producto adquirido por unidad (venta normal) y otro producto adquirido por volumen (venta grande), o aplicar descuentos mixtos. Forzar un filtro de nivel fila sobre una métrica de cabecera como ` Order_ID ` generaría ambigüedades lógicas y duplicidades inconsistentes.

---

### 4.7. Ratios e Indicadores Relativos: Uso de DIVIDE

Los ratios permiten analizar proporciones estructurales entre magnitudes correlacionadas.

#### Ratio de Eficiencia de Ventas (Retención de Margen Bruto vs. Neto)

Evalúa qué porcentaje del valor de lista o venta bruta se retiene efectivamente en caja tras la política de descuentos comerciales:

```javascript
Sales Ratio = DIVIDE([Total Net Sales], [Total Gross Sales], 0)
```

- **Ventaja técnica de DIVIDE:** A diferencia del operador de barra diagonal (` / `), ` DIVIDE ` gestiona automáticamente los casos de división por cero o denominadores nulos sin arrojar errores fatales en los visuales, permitiendo definir un valor por defecto (tercer parámetro opcional, típicamente 0).

- **Interpretación analítica:** Un ratio del 90% indica que la empresa conserva 90 centavos por cada dólar facturado en lista, sacrificando un 10% en descuentos para incentivar la rotación o fidelización.

---

### 4.8. Validación y Comprobación Iterativa del Modelo

- **Verificación inmediata:** Tras escribir cada fórmula DAX, el analista debe validar el resultado en una tabla o matriz visual vinculada a una dimensión (` Stores `, ` Categories `, ` Date `).

- **Pautas de detección de errores:**

  - Celdas en blanco o repetición idéntica del valor total en todas las filas de la dimensión: Indican relaciones rotas o fórmulas DAX mal contextualizadas.
  
  - Consistencia de sumas parciales: La suma de ` Total Net Sales Big Sales ` y ` Total Net Sales Normal Sales ` debe coincidir con exactitud matemática con ` Total Net Sales `.
