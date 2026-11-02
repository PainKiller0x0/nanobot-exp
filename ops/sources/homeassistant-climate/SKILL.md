---
name: home-assistant
description: Use the configured Home Assistant MCP for device lookup and ordinary controls; use the restricted climate bridge only for the Shenzhen AC mode, fan, and swing controls.
metadata:
  nanobot:
    always: true
---

# Home Assistant: Assist MCP and restricted Shenzhen climate bridge

Use the configured `home_assistant` MCP for device lookup, on/off control, and temperature changes. Never use the legacy `/root/.nanobot/workspace/bin/ha` CLI or claim that CLI failed.

Available MCP tools:
- `mcp_home_assistant_homeassistant_GetLiveContext` for current exposed device/area context and state.
- `mcp_home_assistant_intent_HassTurnOn` and `mcp_home_assistant_intent_HassTurnOff` for device control.
- `mcp_home_assistant_light_HassLightSet` for light attributes.
- `mcp_home_assistant_climate_HassClimateSetTemperature` for climate temperature.

## Shenzhen air conditioner: mode, fan, and swing

For explicit requests to query or change the Shenzhen apartment living-room AC's HVAC mode, fan speed, or swing, use only `home_assistant_shenzhen_climate_control`:

- Fixed target: `climate.lumi_cn_917507975_mcn02`, “米家空调伴侣2 空调” in “深圳泊寓 客厅”. The tool accepts no entity, area, or service parameter.
- Call `read_state` to inspect current values and the live options when needed.
- HVAC modes currently exposed: `auto` (自动), `cool` (制冷), `dry` (除湿), `heat` (制热), `fan_only` (送风), `off` (关闭).
- Fan options currently exposed: 自动、低、中、高.
- Swing options currently exposed: `vertical` (上下扫风) and `off` (关闭). Fixed left/right angles are not exposed by this entity.
- Set only an option present in the tool's current read-back. The tool itself checks the live option list before sending a request.
- Report a change as successful only when the tool result explicitly says “已确认” after reading back the requested value. If not, say it was not verified.

Use the climate bridge only when the latest user message explicitly asks to query or change one of these AC features. A casual mention, past-tense description, or discussion about an AC is not authorization to call it.

The bridge is deliberately limited to mode, fan, and vertical swing. Do not use it for temperature, on/off, countdowns/timers, other devices, or arbitrary Home Assistant services. Do not reveal, request, copy, or log the root-only HA token; the bridge reads it internally.

## Interpret device-control intent

Judge authorization from the latest user message itself:
- A direct instruction such as “把 X 打开/关掉” explicitly authorizes that action.
- Mentioning a device, describing its state, or discussing a past action alone does not authorize a change.
- Treat it as an opt-out only if the latest user message explicitly says not to use Home Assistant or not to operate the device. Never infer an opt-out from an earlier assistant refusal, a quoted response, old troubleshooting context, or an instruction to use SSH instead of a dashboard.

For ordinary on/off requests, resolve the requested area and device using current MCP context, then target the unique match. Use the exact name and area returned by Home Assistant. Never claim success when no unique match exists.

For the Shenzhen “米家显示器挂灯2”, the verified entity is `light.xiaomi_cn_2055583470_bar2_s_2_light`; its exact Home Assistant friendly name is `米家显示器挂灯2  灯` (two spaces before 灯), in area `深圳泊寓 客厅`.

After every requested state change, rely on the tool's live state read-back. Do not turn a failed tool result into a success claim. Never claim a tool call or error that did not occur. Ask before safety-sensitive device actions such as locks, alarms, garage doors, or hazardous appliances.