import DocPage from '../components/doc-page';
import { docMetadata, loadDoc } from '../../lib/docs';
import { latestRelease } from '../../lib/release';

const doc = loadDoc('cookbook');

export const metadata = docMetadata(doc);

export default async function Cookbook() {
  return <DocPage doc={loadDoc('cookbook', await latestRelease())} />;
}
