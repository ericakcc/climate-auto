# Skew-T / Log-P Diagram Complete Reference

## I. Diagram Structure

The Skew-T / Log-P diagram plots atmospheric sounding data:
- **Y-axis**: Pressure (mb/hPa), logarithmic scale, decreasing upward
- **X-axis**: Temperature (°C), skewed diagonally to the right
- **Height scales**: Left side in meters, right side in thousands of feet

### Line Types on the Diagram

| Line | Style | Description |
|------|-------|-------------|
| Isotherms | Solid diagonal | Lines of constant temperature (°C) |
| Isobars (Pressure levels) | Solid horizontal | Lines of constant pressure |
| Dry adiabats | Curved, lesser slope | Drawn at 2° intervals |
| Moist adiabats | Curved, steeper/more vertical | Saturated adiabatic lapse rate |
| Mixing ratio lines | Dashed | Lines of constant mixing ratio (g/kg) |

### Sounding Data Plotted
- **Temperature sounding**: Environmental temperature at each pressure level
- **Dewpoint temperature**: Dewpoint at each pressure level
- **Wind barbs**: Wind speed and direction near the height axis (left edge)

---

## II. Key Levels

### a. Lifting Condensation Level (LCL)
- Level where a parcel first becomes saturated when lifted dry adiabatically
- **How to find**: Intersection of the dry adiabat through the temperature at the surface and the mixing ratio line through the dewpoint at the surface

### b. Convective Condensation Level (CCL)
- Level where a parcel heated from below will rise adiabatically until saturated
- Good estimate for cumuliform cloud base from surface heating
- **How to find**: Intersection of the mixing ratio through surface dewpoint and the temperature sounding

### c. Level of Free Convection (LFC)
- Level where a parcel first becomes positively buoyant
- **How to find**: Find LCL, then follow the moist adiabat from LCL upward to where it intersects the temperature sounding

### d. Equilibrium Level (EL)
- Level where a positively buoyant parcel becomes negatively buoyant (upper troposphere)
- **How to find**: Follow the moist adiabat through LFC upward until it intersects the temperature sounding again

---

## III. Meteorological Variables

### a. Temperatures

| Variable | Symbol | Definition | How to Find |
|----------|--------|------------|-------------|
| Potential Temperature | Theta (Θ) | Temperature if parcel brought dry adiabatically to 1000mb | Follow dry adiabat from T at pressure level down to 1000mb |
| Equivalent Temperature | T_e | Temperature if all moisture condensed into parcel | Follow moist adiabat from LCL upward to where moist/dry adiabats parallel, then descend dry adiabat to original pressure |
| Equivalent Potential Temperature | Θ_e | Like T_e but brought down to 1000mb | Same as T_e but continue dry adiabat descent to 1000mb |
| Saturated Equivalent Potential Temperature | Θ_es | Θ_e for an unsaturated parcel as if it were saturated | Follow moist adiabat through environmental T (not LCL) upward, then dry adiabat to 1000mb |
| Wet-bulb Temperature | T_w | Minimum temperature from evaporative cooling at constant pressure | Follow moist adiabat through LCL back to original pressure level |
| Wet-bulb Potential Temperature | Θ_w | T_w brought down dry adiabatically to 1000mb | Continue moist adiabat through LCL down to 1000mb |

### b. Vapor Pressures

| Variable | Symbol | How to Find |
|----------|--------|-------------|
| Vapor Pressure | e | Follow isotherm through dewpoint at pressure level up to 622mb; read mixing ratio value (in mb) |
| Saturated Vapor Pressure | e_s | Follow isotherm through temperature at pressure level up to 622mb; read mixing ratio value (in mb) |

### c. Mixing Ratios

| Variable | Symbol | How to Find |
|----------|--------|-------------|
| Mixing Ratio | w | Read mixing ratio line through dewpoint at pressure level |
| Saturated Mixing Ratio | w_s | Read mixing ratio line through temperature at pressure level |

---

## IV. Stability Indices

### a. K-Index
```
K = T_850 + T_d850 + T_d700 - T_700 - T_500
```

| K Range | Thunderstorm Coverage |
|---------|---------------------|
| < 20 | Rare |
| 20-25 | Isolated |
| 26-30 | Widely scattered |
| 31-35 | Scattered |
| > 35 | Numerous |

### b. Lifted Index (LI)
```
LI = T_500 - T_p850
```
T_p is parcel temperature lifted moist adiabatically from surface LCL to 500mb.

| LI Range | Storm Severity |
|----------|---------------|
| > -2 | Weak |
| -3 to -5 | Strong |
| < -5 | Very strong |

### c. Showalter Index (SI)
```
SI = T_850 - T_p850
```
Like LI but uses 850mb as starting level. Good for elevated thunderstorms.

### d. Total Totals Index (TT)
```
TT = T_850 + T_d850 - 2*T_500
```

| TT Range | Severe Thunderstorm Probability |
|----------|-------------------------------|
| < 44 | Unlikely |
| 44-48 | Scattered, non-severe |
| 48-52 | Few severe |
| > 52 | Many severe |

### e. CAPE (Convective Available Potential Energy)
- Area between moist adiabat (from LFC) and temperature sounding, up to EL
- Positive area = buoyant energy available

### f. CIN (Convective Inhibition)
- Negative area between temperature sounding and parcel ascent path below LFC
- Represents energy barrier a parcel must overcome

### g. DCAPE (Downdraft CAPE)
- Energy of a saturated downdraft falling to surface
- Find LCL at 600mb, descend moist adiabat to surface, measure area between this line and temperature sounding

### h. Cap Strength
- Maximum temperature deficit below LFC
- Values > 2K = large cap, thunderstorm initiation unlikely

---

## V. Cloud Layers

### Shallow Cloud Layers
- Where dewpoint and temperature curves are very close for a short vertical layer

### Deep Cloud Layers
- Where dewpoint and temperature curves are near same magnitude for deep vertical extent
- Sudden drop in dewpoint = condensation occurred (cloud present)
- Significant drop in mixing ratio also indicates cloud

---

## VI. Atmospheric Mixing

### Well-Mixed Atmosphere Indicators
1. Mixing ratio nearly constant with height (dewpoint curve parallels mixing ratio line)
2. Potential temperature nearly constant with height (temperature sounding parallels dry adiabat)

### Alternative Method
- Compare LCL (from surface T and Td) to observed cloud base
- Close match = well mixed; large difference = moderate mixing only

---

## VII. Atmospheric Static Stability

### Using Lapse Rates
Compare environmental lapse rate (Γ) to dry (Γ_d) and moist (Γ_w) adiabatic lapse rates:

| Condition | Stability |
|-----------|-----------|
| Γ < Γ_w | Absolutely stable |
| Γ_w < Γ < Γ_d | Conditionally unstable |
| Γ > Γ_d | Absolutely unstable |

### Using Potential Temperature (Θ)
| ∂Θ/∂z | Stability |
|--------|-----------|
| > 0 | Stable |
| = 0 | Neutral |
| < 0 | Unstable |

### Using Saturated Equivalent Potential Temperature (Θ_es)
| ∂Θ_es/∂z | Stability |
|-----------|-----------|
| > 0 | Stable |
| < 0 | Conditionally unstable |

---

## VIII. Wind Shear

Wind barbs on the left edge of the diagram show speed and direction at various heights.
- **Speed shear**: Abrupt change in wind speed over short distance
- **Directional shear**: Abrupt change in wind direction over short distance
- Critical for strong thunderstorm development and atmospheric waves
