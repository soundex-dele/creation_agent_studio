import {
  ApartmentOutlined,
  AppstoreOutlined,
  BankOutlined,
  BulbOutlined,
  ClockCircleOutlined,
  CodeOutlined,
  CompassOutlined,
  DatabaseOutlined,
  ExperimentOutlined,
  HomeOutlined,
  MessageOutlined,
  ReadOutlined,
  RobotOutlined,
  RocketOutlined,
  StarOutlined,
  TeamOutlined,
  ThunderboltOutlined,
  ToolOutlined,
} from '@ant-design/icons';
import type { NavigationIconId } from './headerNavigation';

export const NAVIGATION_ICON_COMPONENTS = {
  home: HomeOutlined,
  message: MessageOutlined,
  robot: RobotOutlined,
  compass: CompassOutlined,
  bolt: ThunderboltOutlined,
  apps: AppstoreOutlined,
  workflow: ApartmentOutlined,
  book: ReadOutlined,
  clock: ClockCircleOutlined,
  building: BankOutlined,
  bulb: BulbOutlined,
  star: StarOutlined,
  experiment: ExperimentOutlined,
  code: CodeOutlined,
  database: DatabaseOutlined,
  team: TeamOutlined,
  tool: ToolOutlined,
  rocket: RocketOutlined,
} as const;

export const getNavigationIconComponent = (iconId: NavigationIconId) => (
  NAVIGATION_ICON_COMPONENTS[iconId] ?? HomeOutlined
);
