export interface GeoJSONLayer {
  id: string
  name: string
  filePath: string
  visible: boolean
  data: any
  color: string
}

export interface MapViewState {
  center: [number, number]
  zoom: number
  bearing: number
  pitch: number
}

/** Saved map extent + view for quick navigation */
export interface MapBookmark {
  id: string
  name: string
  south: number
  west: number
  north: number
  east: number
  zoom: number
}

export interface DrawStyleConfig {
  fillColor: string
  strokeColor: string
  fillOpacity: number
  lineWidth: number
  lineDash: 'solid' | 'dashed' | 'dotted'
}

export interface ZonePreset {
  code: string
  label: string
  color: string
  description: string
}

export const DEFAULT_ZONE_PRESETS: ZonePreset[] = [
  { code: 'R1', label: 'Residential (low)', color: '#fef08a', description: 'Low-density residential' },
  { code: 'R2', label: 'Residential (med)', color: '#facc15', description: 'Medium-density residential' },
  { code: 'C1', label: 'Commercial', color: '#fca5a5', description: 'Retail / office commercial' },
  { code: 'I1', label: 'Industrial', color: '#c4b5fd', description: 'Industrial / logistics' },
  { code: 'G', label: 'Greenspace', color: '#86efac', description: 'Parks, agriculture, open space' },
  { code: 'MX', label: 'Mixed use', color: '#fdba74', description: 'Mixed residential-commercial' },
  { code: 'INST', label: 'Institutional', color: '#93c5fd', description: 'Schools, hospitals, civic' },
]

export const DEFAULT_DRAW_STYLE: DrawStyleConfig = {
  fillColor: '#3b82f6',
  strokeColor: '#1d4ed8',
  fillOpacity: 0.35,
  lineWidth: 2,
  lineDash: 'solid',
}

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: number
}

export interface Conversation {
  id: string
  title: string
  messages: ChatMessage[]
  createdAt: number
}

export interface MapAction {
  type: string
  payload: Record<string, any>
}

export interface ProjectData {
  version: number
  mapState: MapViewState
  layers: Array<{
    name: string
    filePath: string
    visible: boolean
    color: string
  }>
  drawnFeatures: any[]
  conversations: Conversation[]
  activeConversationId: string | null
  chatHistory?: ChatMessage[]
  basemap: string
  bookmarks?: MapBookmark[]
}

export interface MapContext {
  center: [number, number]
  zoom: number
  bounds?: { west: number; south: number; east: number; north: number }
  bookmarks: Array<{
    name: string
    south: number
    west: number
    north: number
    east: number
    zoom: number
  }>
  layers: Array<{
    name: string
    featureCount: number
    geometryTypes: string[]
    properties: string[]
    visible: boolean
    geometry_data?: any
  }>
  drawnFeatures: Array<{
    type: string
    coordinates?: any
  }>
  basemap: string
}

export const LAYER_COLORS = [
  '#e6194b', '#3cb44b', '#4363d8', '#f58231', '#911eb4',
  '#42d4f4', '#f032e6', '#bfef45', '#fabed4', '#469990',
]

export const BASEMAPS: Record<string, { name: string; tiles: string[]; attribution: string }> = {
  street: {
    name: 'Street',
    tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenStreetMap contributors',
  },
  satellite: {
    name: 'Satellite',
    tiles: [
      'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    ],
    attribution: '&copy; Esri',
  },
  dark: {
    name: 'Dark',
    tiles: ['https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png'],
    attribution: '&copy; CartoDB',
  },
  terrain: {
    name: 'Terrain',
    tiles: ['https://tile.opentopomap.org/{z}/{x}/{y}.png'],
    attribution: '&copy; OpenTopoMap',
  },
}
