# SGBC Data Model

Django-first provenance model for biospecimens, biosamples, activities, and
their versioned information records.

## Development

The project uses Django-managed models with MySQL. The Compose database is
named `sgbc_django`.

```bash
docker compose up -d --build
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Open the admin at <http://localhost:8000/admin/>.

Models are declared in `datamodel_demo/app1/models.py`; migrations are the
source of truth for the database schema. Do not use `inspectdb` or import the
legacy SQL files for this branch.

## Useful commands

```bash
docker compose exec web python manage.py makemigrations app1
docker compose exec web python manage.py migrate
docker compose exec web python manage.py check
```

The legacy conceptual DBML and SQL artifacts remain in the repository for
reference.

## Schema utilities

Use `app1.utils` to create validated entities and activities, append information
records, traverse provenance, query/group by type, and validate existing entries.
See [the utility API and examples](docs/schema_utilities.md).

JSON fixtures can be loaded with `python manage.py load_json_fixture path.json`
(use `-` for stdin). The format is documented in [example_fixture.json](docs/example_fixture.json).

To export a populated, complete provenance record as JSON, select any entity in
the connected graph:

```bash
python manage.py export_provenance B001-fixed -o provenance.json
```

The export preserves the graph rather than flattening it into a tree: it includes
all linked entities and activities, every sidecar revision and parameter, port
edges, provenance boundaries, external references, relations, agents, and
protocols. Its format is documented in [schema_utilities.md](docs/schema_utilities.md).

Run local tests without a database service:

```bash
cd datamodel_demo
python manage.py test app1 --settings=datamodel_demo.test_settings
```

## Spatial viewer

The spatial viewer is available at `/spatial/` and defaults to the real
mouse-liver SpatialData demo. Download the versioned, CC BY 4.0 sample store
before starting the app:

```bash
./scripts/download_spatialdata_demo.sh
docker compose up -d --build
```

Open <http://localhost:8000/spatial/>. The reader loads the image, segmentation,
cell coordinates, annotations, and raw gene counts from Zarr; source data stays
outside MySQL and is excluded from Git. The synthetic development dataset
remains available at `/spatial/synthetic-demo/`.

The API uses bounded, gene-targeted responses rather than sending the expression
matrix to the browser:

```text
/api/spatial/
/api/spatial/<dataset_id>/metadata/
/api/spatial/<dataset_id>/coordinates/?xmin=...&xmax=...&ymin=...&ymax=...
/api/spatial/<dataset_id>/expression/?gene=Gene_0&limit=50000
/api/spatial/<dataset_id>/image/
/api/spatial/<dataset_id>/mask/
```

To register a real provenance entity as a future spatial dataset, add a
`spatial_dataset` object to the latest `EntityInformationRecord.metadata` for
that entity. The object may declare `name`, `description`, `layers`, `genes`,
`n_bins`, and `n_genes`. The graph links registered entities to
`/spatial/entity-<id>/`; until a compatible reader is installed, the viewer
reports the dataset as registered but unavailable rather than fabricating data.
# SGBC_data_model

*I want to make a data model including biospecimen and biosample, which models relationships through the abstraction of Activity - eg in post mortem whole brain histology, the biospecimen is the donor, and the activity of extraction produces the biosample 'brain'. Now the biosample can again be acted upon, like perfusion, fixation, freezing, storing, etc, each producing an artifact. I want to model this using dbml*

Source discussion:
https://chatgpt.com/share/6a9bee09-d694-83ee-aecf-85ab059ac5a2

## High level ontology
<pre>
                    ENTITY
                      │
          ┌───────────┼──────────────┐
          │           │              │
 BiologicalSource  Material       Digital
     Donor          Entity         Entity
                     │
             ┌───────┴───────┐
          Biospecimen      Biosample

                     ↑
                     │
                   input
                     │
                  ACTIVITY
                     │
                   output
                     ↓

                    ENTITY
</pre>

### Accessioning 

                 ENTITY ORIGIN
                      │
          ┌───────────┼─────────────┐
          │           │             │
       Derived     Accessioned    Created
          │           │             │
    known input    no local       no material
      entities      input           input
          │           │             │
    sectioning     tissue         annotation
    extraction     received       segmentation
    staining       externally     generated data

## Activity type
<pre>
processing
├── extraction
├── preservation
│   ├── perfusion
│   ├── fixation
│   ├── cryoprotection
│   ├── freezing
│   └── storage
├── dissection
│   ├── hemisphere_separation
│   ├── slabbing
│   └── block_extraction
├── sectioning
├── staining
│   ├── Nissl
│   ├── H&E
│   ├── Myelin
│   └── IHC
└── acquisition
    ├── slide_scanning
    ├── MRI
    └── spatial_transcriptomics
</pre>

## Activity is Multi-input multi-output 

0 → N    accession/source
1 → 1    fixation
1 → N    sectioning/slabbing
N → 1    pooling/merging
N → N    registration, fusion, multiplexed processing
N → 0    disposal/transfer-out

## Abstract, concrete, materialized

| EntityType         | Concrete? | Tier-3 materialized? |
| ------------------ | --------: | -------------------: |
| BiologicalMaterial |        No |                   No |
| Biospecimen        |        No |                   No |
| WholeBrain         |       Yes |                  Yes |
| TissueBlock        |       Yes |                  Yes |
| Section            |       Yes |                  Yes |
| ReagentLot         |       Yes |                   No |
| DigitalArtifact    |        No |                   No |
| WSI                |       Yes |                  Yes |
| QCImage            |       Yes |                   No |



## Information sidecars
*i want to implement sidecar information records for all entities and also activities. The information record decouples the entity's mutable fields from the immutable ones (which will be attributes in the entity). Also the information record for the activity captures the set of process parameters (name,value pairs)*

<pre>
ENTITY
    immutable assertion:
    "this thing exists"

INFORMATION RECORD
    temporal assertion:
    "these facts are currently known about this thing"

ACTIVITY
    immutable assertion:
    "this event exists"

INFORMATION RECORD
    temporal assertion:
    "these are the currently known properties of that event"
</pre>

Example:

<pre>
Brain B001
   │
   ├── AnatomicalInformationRecord
   │      whole brain
   │      hemisphere status
   │      orientation
   │
   ├── StorageInformationRecord
   │      freezer
   │      shelf
   │      temperature
   │
   └── QCInformationRecord
          tissue integrity
          fixation quality
</pre>

<pre>
                         ┌────────────────────┐
                         │       Entity       │
                         │ immutable identity │
                         └─────────┬──────────┘
                                   │
                            has information
                                   │
                    ┌──────────────▼──────────────┐
                    │ Entity Information Record   │
                    │ versioned / mutable state   │
                    └─────────────────────────────┘
</pre>

<pre>
Entity ── input ──► Activity ── output ──► Entity
                        │
                        │ has information
                        ▼
              ┌──────────────────────────┐
              │ Activity Information     │
              │ Record                   │
              └────────────┬─────────────┘
                           │
                         has
                           ▼
                  Activity Parameter
                  name/value/unit
</pre>

<pre>
                   no known input
                        │
                        ▼
                  Accession Activity
                        │
             ActivityInformationRecord
                        │
         source institution = ...
         received date = ...
         external id = ...
                        │
                        ▼
                   Brain Entity
                        │
                        ▼
             EntityInformationRecord
</pre>

## Information schema

| Model | What it represents | Example |
|---|---|---|
| `ActivityType` | Category of operation | Fixation |
| `Activity` | One specific event | Fixation event `FIX-001` |
| `Protocol` | Intended procedure, with a version | Whole Brain Fixation, v1.0 |
| `ActivityInformationRecord` | Recorded details of that event | Protocol used, operator, timing, status |
| `ProtocolParameter` | Expected parameters | Target duration: 72 hours |
| `ActivityParameter` | Actual execution parameters | Recorded duration: 76 hours |

## DB diagram
<pre>
                               Agent
                                 |
                                 |
EntityInformationRecord       ActivityInformationRecord
          |                         |
          |                         +---- ActivityParameter
          |                         |
          v                         v
       ENTITY ---- input ----> ACTIVITY ---- output ----> ENTITY
                                   |
                                   |
                               Protocol
</pre>
https://dbdiagram.io/d/SGBC_data_model-6a9bea4f5450bea1bef885bb


## Summary

| Situation                        | Representation                                  |
| -------------------------------- | ----------------------------------------------- |
| Tissue extracted internally      | `Donor → Extraction → Brain`                    |
| Tissue received externally       | `0 → Accession → Brain`                         |
| Brain fixed                      | `Brain → Fixation → Fixed Brain state`          |
| Brain physically divided         | `Brain → Dissection → Hemisphere(s)`            |
| Metadata correction              | new `EntityInformationRecord`                   |
| Process parameter correction     | new `ActivityInformationRecord` + parameter set |
| Protocol changed                 | new/versioned `Protocol`                        |
| Unknown upstream source          | provenance boundary at `Accession`              |
| External source identifier known | `ExternalReference`                             |
| Image derived from tissue        | `Slide → Imaging → Image`                       |
| Segmentation derived from image  | `Image → Segmentation Activity → Mask`          |

## Django demo project and app

<pre>
pip install django mysqlclient django-unfold

django-admin startproject datamodel_demo

cd datamodel_demo

python manage.py startapp app1
</pre>

## Django development environment

The demo Django project uses MySQL through Docker Compose. Start the database
and development server from the repository root:

```bash
docker compose up --build
```

The Django server is available at http://localhost:8000. Open the admin at
http://localhost:8000/admin/ and run management
commands in the web container, for example:

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser
```

Run Django management commands through `docker compose exec web` so the
Compose hostname `db` resolves correctly. If running them directly on the
host, use `python manage.py ...`; the settings default to `127.0.0.1`, which
uses the published MySQL port.

You can connect interactively with:

```bash
docker compose exec db mysql -usgbc -psgbc_dev_password sgbc
```

Stop the services with `docker compose down`. The named `mysql_data` volume
keeps the database between restarts; use `docker compose down -v` to remove it.

The script reads the table names from `SGBC_data_model.sql`, runs `inspectdb`
inside the web container, writes `datamodel_demo/app1/models.py`, and runs
`manage.py check`. The models are automatically registered in Django admin.
