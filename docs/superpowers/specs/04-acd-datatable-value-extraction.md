# SPEC-04: Offline ACD Data-Table Value & Preset Extraction

**Status:** Backlog Target (BUG-02 / Issue #23, Ranked Feature #3)  
**Priority:** P1 / High  
**Subsystem:** `acd` (`src/acd/l5x/elements.py`, `src/acd/record/dat_table.py`)  
**Audit References:** [§6 BUG-02](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#bug-02-p1-convert_acd-to-l5x-hardcodes-all-data-table-values-to-zero), [§11 ACD ↔ L5X Parity Matrix](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#11-acd--l5x-parity-matrix), [§26 Ranked Feature #3](file:///home/hello/git/work/studio5000-AI-Assistant/docs/ENGINEERING_AUDIT_2026.md#26-ranked-feature-opportunities)

---

## 1. Problem Statement & Background

When converting an offline Rockwell `.ACD` file to `.L5X` via `convert_acd_to_l5x`, the current implementation in `src/acd/l5x/elements.py:160-280` hardcodes all tag data-table values, member defaults, timer presets (`.PRE`), accumulator values (`.ACC`), and configuration limits to zero (`_PRIMITIVE_DECORATED_ZERO = "0"`).

### Impact on Industrial Static Analysis:
1. **Broken SCADA Scaling Limits:** Analog scaling limits (`RawMin`/`RawMax`, `MinEU`/`MaxEU`) export as zeros. The Ignition exporter cannot determine real instrument engineering spans.
2. **False Zero-Range Warnings:** Static analyzers inspecting timer presets flag all timers as zero-delay faults (`TON` with preset 0).
3. **Loss of Setpoints:** Setpoints, PID tuning parameters ($K_p, K_i, K_d$), and recipe values are lost when inspecting projects offline without a live controller connection.

---

## 2. ACD Data-Table Storage Architecture

In Studio 5000 v38 `.ACD` archives, tag runtime values and default initialization values are stored within binary data records (`Dat` streams / `TagData.Dat`):

```mermaid
graph TD
    subgraph ACDContainer["ACD Container Streams"]
        Comps["Comps.Dat\n(Tag Definitions & Data Type IDs)"]
        DataStream["Dat Streams\n(Byte Arrays / Struct Records)"]
        DataTypes["DataTypes / UDT Definitions"]
    end

    subgraph ValueDecoder["Data-Table Byte Decoder (src/acd/record/dat_table.py)"]
        Parser["DatRecord Byte Parser"]
        Align["Struct Alignment & Member Offset Calculator"]
        Unpack["Type-Specific Unpacker (IEEE-754 REAL, Little-Endian DINT/INT/SINT/BOOL)"]
    end

    subgraph L5XSerializer["L5X Value Serializer (src/acd/l5x/elements.py)"]
        DecoratedXML["DecoratedData XML Builder\n<Data Format=\"Decorated\">\n<DataValue DataType=\"REAL\" Value=\"125.5\"/>"]
    end

    Comps --> Align
    DataTypes --> Align
    DataStream --> Parser
    Parser --> Unpack
    Align --> Unpack
    Unpack --> DecoratedXML
```

### Data Type Encodings:
- **`BOOL`**: Packed as single bits within 32-bit DINT containers for atomic tags, or 8-bit byte aligned within UDT byte layouts.
- **`SINT`**: 1 byte signed integer (`int8`).
- **`INT`**: 2 bytes little-endian signed integer (`int16`).
- **`DINT`**: 4 bytes little-endian signed integer (`int32`).
- **`LINT`**: 8 bytes little-endian signed integer (`int64`).
- **`REAL`**: 4 bytes IEEE-754 single-precision float (`float32`).
- **`LREAL`**: 8 bytes IEEE-754 double-precision float (`float64`).
- **`TIMER` / `COUNTER`**: Built-in 12-byte structs:
  - `TIMER`: `Flags (DINT)`, `PRE (DINT)`, `ACC (DINT)`
  - `COUNTER`: `Flags (DINT)`, `PRE (DINT)`, `ACC (DINT)`
- **`STRING`**: `LEN (DINT)` followed by byte array (up to max characters).

---

## 3. Implementation Specification

### 3.1 Binary Unpacker Interface (`src/acd/record/dat_table.py`)

```python
import struct
from typing import Any, Dict, Optional

class TagValueDecoder:
    def __init__(self, dat_records: bytes, data_types: Dict[str, Any]):
        self.dat_records = dat_records
        self.data_types = data_types

    def decode_tag_value(
        self,
        tag_record_offset: int,
        data_type_name: str,
        dimensions: int = 0
    ) -> Any:
        """
        Decodes the raw bytes at tag_record_offset according to data_type_name.
        Returns scalar primitive, dict of member values for UDTs, or list for arrays.
        """
```

### 3.2 L5X Decorated XML Output Generation (`src/acd/l5x/elements.py`)

Replace `_PRIMITIVE_DECORATED_ZERO` with dynamically formatted XML nodes:

```python
def format_decorated_data_value(data_type: str, value: Any) -> str:
    """Formats scalar or structured value into valid Studio 5000 L5X DecoratedData XML."""
    if data_type == "REAL":
        return f'<DataValue DataType="REAL" Value="{float(value):.7g}"/>'
    elif data_type in ("DINT", "INT", "SINT", "LINT"):
        return f'<DataValue DataType="{data_type}" Value="{int(value)}"/>'
    elif data_type == "BOOL":
        return f'<DataValue DataType="BOOL" Value="{1 if value else 0}"/>'
    elif data_type == "TIMER":
        return (
            f'<Structure DataType="TIMER">'
            f'<DataValueMember Name="PRE" DataType="DINT" Value="{value.get("PRE", 0)}"/>'
            f'<DataValueMember Name="ACC" DataType="DINT" Value="{value.get("ACC", 0)}"/>'
            f'<DataValueMember Name="EN" DataType="BOOL" Value="{1 if value.get("EN") else 0}"/>'
            f'<DataValueMember Name="TT" DataType="BOOL" Value="{1 if value.get("TT") else 0}"/>'
            f'<DataValueMember Name="DN" DataType="BOOL" Value="{1 if value.get("DN") else 0}"/>'
            f'</Structure>'
        )
    # Recursively render UDT members...
```

---

## 4. Testing & Acceptance Criteria

### 4.1 Unit Tests (`tests/acd/test_dat_table_values.py`)
- Unpack scalar primitive types (`BOOL`, `SINT`, `INT`, `DINT`, `REAL`) from mock binary streams.
- Unpack `TIMER` and `COUNTER` structures with non-zero `PRE` and `ACC` values.
- Unpack multi-level nested UDT structures.

### 4.2 Integration Tests
- Run `convert_acd_to_l5x` on `tests/acd/KemcoWaterHeater/Kemco_HA105.ACD`.
- Verify extracted values for analog scaling parameters:
  - `Htr1_Temp_RawMin` $\neq 0$ (matches actual 4000 raw counts).
  - `Htr1_Temp_RawMax` $\neq 0$ (matches actual 20000 raw counts).
- Run `extract_analog_scaling` on the converted L5X and confirm scaling ranges are discovered accurately.

### 4.3 Acceptance Criteria
- Tag values in converted L5X files represent the actual saved snapshot values from the `.ACD` file rather than default zeros.
